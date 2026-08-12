import os, json, csv, sys, base64, threading
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext
 
# ── Config ─────────────────────────────────────────────────────────────
BASE_URL   = os.getenv("BASE_URL",   "https://gps-backend-pqzg.onrender.com")
SECRET     = os.getenv("SECRET",     "HERMES_SECRET_2025")
DEVICE_KEY = os.getenv("DEVICE_KEY", "HERMES_DEVICE_KEY_123")
ADMIN_USER = os.getenv("ADMIN_USER", "Hermesadmin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Colombia2026*")
 
# ── GitHub persistencia ────────────────────────────────────────────────
# Variables de entorno en Render:
#   GH_TOKEN  = tu personal access token de GitHub (repo scope)
#   GH_REPO   = usuario/repositorio  (ej: jhonlopez38/pruebas)
#   GH_BRANCH = rama (ej: main)
GH_TOKEN  = os.getenv("GH_TOKEN",  "")
GH_REPO   = os.getenv("GH_REPO",   "")
GH_BRANCH = os.getenv("GH_BRANCH", "main")
USE_GITHUB = bool(GH_TOKEN and GH_REPO)
 
if USE_GITHUB:
    print(f"[HERMES] GitHub persistencia: {GH_REPO} ({GH_BRANCH})", file=sys.stderr)
else:
    print("[HERMES] Sin GitHub — datos en disco local", file=sys.stderr)
 
# ── Rutas locales ──────────────────────────────────────────────────────
STATIC_DIR   = "static"
FILES_DIR    = "static/files"
DATA_DIR     = "data"
CSV_PATH     = os.path.join(FILES_DIR, "gps_log.csv")
KML_PATH     = os.path.join(FILES_DIR, "ruta.kml")
COMMAND_FILE = os.path.join(FILES_DIR, "command.json")
STATUS_FILE  = os.path.join(FILES_DIR, "status.json")
USERS_FILE   = os.path.join(DATA_DIR,  "users.json")
DEVICES_FILE = os.path.join(DATA_DIR,  "devices.json")
HISTORY_FILE = os.path.join(DATA_DIR,  "history.json")
 
for d in [STATIC_DIR, FILES_DIR, DATA_DIR]:
    os.makedirs(d, exist_ok=True)
 
# ── App ────────────────────────────────────────────────────────────────
app = FastAPI(title="HERMES GPS Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
 
# ── PWA: manifest y service worker ─────────────────────────────────────
# Android solo ofrece "Instalar app" si la pagina sirve un manifest valido
# Y registra un service worker. Sin estos dos endpoints ambos daban 404 y
# el navegador nunca lanzaba el evento de instalacion.
PWA_MANIFEST = {
    "name": "HERMES GPS Tactico",
    "short_name": "HERMES",
    "description": "Sistema de rastreo GPS tactico HERMES",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "any",
    "background_color": "#0a1628",
    "theme_color": "#0a1628",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    ],
}
 
SW_JS = """
const CACHE = 'hermes-v1';
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => {
  // Red primero: los datos GPS deben estar siempre frescos.
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
"""
 
# Iconos PNG generados al vuelo con el logo HERMES (triangulo + circulo), para
# no depender de ficheros binarios en el repositorio. Se cachean en memoria:
# solo se dibujan la primera vez que el navegador los pide.
_ICONOS_CACHE = {}
 
def _icono_png(lado: int) -> bytes:
    if lado in _ICONOS_CACHE: return _ICONOS_CACHE[lado]
    import struct, zlib, math
    BG, CYAN, GRN = (0x0A,0x16,0x28), (0x00,0xC8,0xFF), (0x00,0xFF,0x88)
    OUT = [(20,3),(37.5,36),(2.5,36)]
    IN  = [(20,10),(31,32),(9,32)]
    CX, CY, CR, ORB = 20.0, 26.0, 3.6, 8.2
    SS  = 2
    def d_seg(px,py,ax,ay,bx,by):
        vx,vy=bx-ax,by-ay; wx,wy=px-ax,py-ay
        L=vx*vx+vy*vy
        t=0.0 if L==0 else max(0.0,min(1.0,(wx*vx+wy*vy)/L))
        return math.hypot(ax+t*vx-px, ay+t*vy-py)
    def d_poly(px,py,pts):
        return min(d_seg(px,py,pts[i][0],pts[i][1],
                         pts[(i+1)%len(pts)][0],pts[(i+1)%len(pts)][1])
                   for i in range(len(pts)))
    esc = 40.0/lado
    filas = []
    for y in range(lado):
        fila = bytearray()
        for x in range(lado):
            ac=[0.0,0.0,0.0]
            for sy in range(SS):
                for sx in range(SS):
                    ux=(x+(sx+0.5)/SS)*esc; uy=(y+(sy+0.5)/SS)*esc
                    col=BG
                    if abs(math.hypot(ux-20.0,uy-20.0)-ORB) < 0.28:
                        col=tuple(int(BG[i]+(GRN[i]-BG[i])*0.28) for i in range(3))
                    if d_poly(ux,uy,IN) < 0.35:
                        col=tuple(int(BG[i]+(CYAN[i]-BG[i])*0.40) for i in range(3))
                    if d_poly(ux,uy,OUT) < 1.15: col=CYAN
                    if math.hypot(ux-CX,uy-CY) < CR: col=CYAN
                    for i in range(3): ac[i]+=col[i]
            n=SS*SS
            fila += bytes([int(ac[0]/n), int(ac[1]/n), int(ac[2]/n)])
        filas.append(b"\x00"+bytes(fila))
    crudo=b"".join(filas)
    def chunk(t,d):
        c=t+d
        return struct.pack(">I",len(d))+c+struct.pack(">I",zlib.crc32(c)&0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB",lado,lado,8,2,0,0,0))
           + chunk(b"IDAT", zlib.compress(crudo,9))
           + chunk(b"IEND", b""))
    _ICONOS_CACHE[lado]=png
    return png
 
@app.get("/manifest.json")
def pwa_manifest():
    return JSONResponse(PWA_MANIFEST, media_type="application/manifest+json")
 
@app.get("/sw.js")
def pwa_service_worker():
    return Response(SW_JS, media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})
 
@app.get("/icon-192.png")
def pwa_icon_192():
    return Response(_icono_png(192), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})
 
@app.get("/icon-512.png")
def pwa_icon_512():
    return Response(_icono_png(512), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})
 
pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)
 
# ══════════════════════════════════════════════════════════════════════
#  GITHUB API — guardar archivos en el repo (persistencia permanente)
# ══════════════════════════════════════════════════════════════════════
_gh_lock = threading.Lock()
 
def gh_get_file(path: str):
    """Obtener contenido y SHA de un archivo en GitHub."""
    try:
        import urllib.request
        url = f"https://api.github.com/repos/{GH_REPO}/contents/{path}?ref={GH_BRANCH}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {GH_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return None
 
def gh_put_file(path: str, content: str, message: str = "HERMES data update"):
    """Crear o actualizar archivo en GitHub."""
    if not USE_GITHUB:
        return False
    try:
        import urllib.request
        existing = gh_get_file(path)
        sha = existing.get("sha") if existing else None
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = json.dumps({
            "message": message,
            "content": encoded,
            "branch":  GH_BRANCH,
            **({"sha": sha} if sha else {})
        }).encode("utf-8")
        url = f"https://api.github.com/repos/{GH_REPO}/contents/{path}"
        req = urllib.request.Request(url, data=payload, method="PUT", headers={
            "Authorization": f"token {GH_TOKEN}",
            "Content-Type":  "application/json",
            "Accept": "application/vnd.github.v3+json"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception as e:
        print(f"[GH] Error guardando {path}: {e}", file=sys.stderr)
        return False
 
def gh_read_json(gh_path: str, local_path: str, default):
    """Leer JSON desde GitHub si disponible, sino desde local."""
    if USE_GITHUB:
        try:
            data = gh_get_file(gh_path)
            if data and data.get("content"):
                raw = base64.b64decode(data["content"]).decode("utf-8")
                result = json.loads(raw)
                # Sincronizar copia local
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(raw)
                return result
        except Exception as e:
            print(f"[GH] Read {gh_path}: {e}", file=sys.stderr)
    return read_json_local(local_path, default)
 
def gh_write_json(gh_path: str, local_path: str, data, async_gh: bool = True):
    """Guardar JSON local inmediatamente, GitHub en background."""
    content = json.dumps(data, indent=2, ensure_ascii=False)
    # Siempre guardar local primero (inmediato)
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(content)
    # Guardar en GitHub (puede ser async para no bloquear el ESP32)
    if USE_GITHUB:
        if async_gh:
            t = threading.Thread(target=gh_put_file, args=(gh_path, content), daemon=True)
            t.start()
        else:
            gh_put_file(gh_path, content)
 
# ══════════════════════════════════════════════════════════════════════
#  HELPERS JSON LOCALES
# ══════════════════════════════════════════════════════════════════════
def read_json_local(path, default):
    if not os.path.exists(path): return default
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except: return default
 
def read_json(path, default):
    return read_json_local(path, default)
 
def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
 
# ══════════════════════════════════════════════════════════════════════
#  INIT — cargar datos desde GitHub al arrancar
# ══════════════════════════════════════════════════════════════════════
def sync_from_github():
    """Al arrancar, descargar archivos de GitHub si están disponibles."""
    if not USE_GITHUB:
        return
    files = [
        ("data/history.json",  HISTORY_FILE,  []),
        ("data/users.json",    USERS_FILE,    {}),
        ("data/devices.json",  DEVICES_FILE,  {}),
        ("static/files/status.json",  STATUS_FILE,  {}),
        ("static/files/command.json", COMMAND_FILE, {}),
    ]
    for gh_path, local_path, default in files:
        try:
            data = gh_get_file(gh_path)
            if data and data.get("content"):
                raw = base64.b64decode(data["content"]).decode("utf-8")
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(raw)
                print(f"[GH] Sincronizado: {gh_path}", file=sys.stderr)
        except Exception as e:
            print(f"[GH] No se pudo sincronizar {gh_path}: {e}", file=sys.stderr)
 
    # Sincronizar CSV
    try:
        data = gh_get_file("static/files/gps_log.csv")
        if data and data.get("content"):
            raw = base64.b64decode(data["content"]).decode("utf-8")
            with open(CSV_PATH, "w", encoding="utf-8") as f:
                f.write(raw)
            print("[GH] Sincronizado: gps_log.csv", file=sys.stderr)
    except Exception as e:
        print(f"[GH] No se pudo sincronizar CSV: {e}", file=sys.stderr)
 
def init_files():
    for path, default in [
        (USERS_FILE, {}), (DEVICES_FILE, {}),
        (HISTORY_FILE, []), (STATUS_FILE, {}),
    ]:
        if not os.path.exists(path): write_json(path, default)
    if not os.path.exists(COMMAND_FILE):
        write_json(COMMAND_FILE, {})
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([
                "id","despertar","fecha","hora","lat","lon",
                "estado","bateria_v","bateria_pct","device","created_at"
            ])
 
# Arranque: primero sincronizar desde GitHub, luego init local
sync_from_github()
init_files()
 
def ensure_admin():
    users = read_json(USERS_FILE, {})
    changed = ADMIN_USER not in users or users[ADMIN_USER].get("role") != "admin"
    users[ADMIN_USER] = {
        "username": ADMIN_USER, "email": ADMIN_USER,
        "name": "Administrador HERMES",
        "password": pwd_ctx.hash(ADMIN_PASS), "role": "admin",
        "created_at": users.get(ADMIN_USER, {}).get("created_at", datetime.utcnow().isoformat()),
        "updated_at": datetime.utcnow().isoformat(),
    }
    write_json(USERS_FILE, users)
    if USE_GITHUB and changed:
        content = json.dumps(users, indent=2, ensure_ascii=False)
        gh_put_file("data/users.json", content)
 
ensure_admin()
 
# ══════════════════════════════════════════════════════════════════════
#  JWT
# ══════════════════════════════════════════════════════════════════════
def create_token(username: str, role: str) -> str:
    return jwt.encode(
        {"sub": username, "role": role, "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET, algorithm="HS256")
 
def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Token requerido")
    try:
        p = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        if not p.get("sub"): raise HTTPException(401, "Token invalido")
        return {"username": p["sub"], "email": p["sub"], "role": p.get("role","user")}
    except JWTError:
        raise HTTPException(401, "Token invalido")
 
def require_admin(user=Depends(get_user)):
    if user["role"] != "admin": raise HTTPException(403, "Solo administrador")
    return user
 
def check_device_key(request: Request):
    if request.headers.get("x-device-key") != DEVICE_KEY:
        raise HTTPException(401, "Device key invalida")
 
# ══════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════
def parse_dt(value):
    if not value: return None
    try: return datetime.fromisoformat(value.replace("Z",""))
    except: return None
 
def capture_dt(p):
    """Fecha/hora REAL de captura del punto (Colombia) convertida a UTC naive.
 
    Se usa para filtrar y ordenar el historial. Es distinto de 'created_at',
    que es cuando el backend RECIBIO el dato: en un reenvio pendiente pueden
    diferir dias, lo que dejaba los puntos fuera de su rango y fuera de orden.
    Si la fecha/hora no es utilizable, se recurre a created_at.
    """
    f = (p.get("fecha") or "").strip()
    h = (p.get("hora")  or "").strip()
    if len(f) == 10 and len(h) >= 5 and h.lower() != "no disponible":
        try:
            d = datetime.strptime(f + " " + h[:8], "%d/%m/%Y %H:%M:%S")
            return d + timedelta(hours=5)   # Colombia (UTC-5) -> UTC
        except Exception:
            pass
    return parse_dt(p.get("created_at", "")) or datetime.min
 
def in_range(created_at, start, end):
    dt = parse_dt(created_at)
    s  = parse_dt(start)
    e  = parse_dt(end)
    if not dt: return True
    try:
        dt = dt.replace(tzinfo=None)
        if s and dt < s.replace(tzinfo=None): return False
        if e and dt > e.replace(tzinfo=None) + timedelta(seconds=59): return False
    except: pass
    return True
 
def valid_point(p):
    try:
        return abs(float(p.get("lat",0) or 0)) > 0.0001 and \
               abs(float(p.get("lon",0) or 0)) > 0.0001
    except: return False
 
# ══════════════════════════════════════════════════════════════════════
#  MODELOS
# ══════════════════════════════════════════════════════════════════════
class RegisterModel(BaseModel):
    username: str = ""; email: str = ""; name: str = ""; password: str
 
class LoginModel(BaseModel):
    username: str = ""; email: str = ""; password: str
 
class UserCreateModel(BaseModel):
    username: str = ""; email: str = ""; password: str; role: str = "user"
    devices: list = []   # IDs de equipos a asignar al crear
 
class DeviceModel(BaseModel):
    device_id: str = ""; device: str = ""; nombre: str = "Sin nombre"
    name: str = ""; icono: str = "antenna"; color: str = "#00c8ff"; owner: str = ""
 
class AssignModel(BaseModel):
    user_email: str; device: str
 
class CommandModel(BaseModel):
    cmd: str; device: str = "HERMES-01"
 
# ══════════════════════════════════════════════════════════════════════
#  COMANDOS
# ══════════════════════════════════════════════════════════════════════
def read_commands() -> dict:
    data = read_json(COMMAND_FILE, {})
    if "cmd" in data and isinstance(data.get("cmd"), str):
        return {data.get("device","HERMES-01"): data}
    return data
 
def write_command(device: str, cmd: str):
    cmds = read_commands()
    cmds[device] = {"device": device, "cmd": cmd,
                    "created_at": datetime.utcnow().isoformat(), "attempts": 0}
    write_json(COMMAND_FILE, cmds)
    if USE_GITHUB:
        t = threading.Thread(target=gh_put_file,
            args=("static/files/command.json", json.dumps(cmds, indent=2)), daemon=True)
        t.start()
 
def get_cmd_for_device(device: str) -> dict:
    return read_commands().get(device, {"cmd": "none"})
 
# ══════════════════════════════════════════════════════════════════════
#  RUTAS
# ══════════════════════════════════════════════════════════════════════
@app.get("/")
def home():
    p = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(p) if os.path.exists(p) else {"ok": True, "msg": "HERMES Backend"}
 
@app.get("/health")
def health():
    history_count = len(read_json(HISTORY_FILE, []))
    return {"ok": True, "time": datetime.utcnow().isoformat(),
            "admin": ADMIN_USER, "github": USE_GITHUB,
            "repo": GH_REPO if USE_GITHUB else None,
            "history_points": history_count}
 
# ── Auth ───────────────────────────────────────────────────────────────
@app.post("/register")
def register(data: RegisterModel):
    users    = read_json(USERS_FILE, {})
    username = (data.username or data.email).strip()
    if not username: raise HTTPException(400, "Usuario requerido")
    if username in users: raise HTTPException(400, "Usuario ya existe")
    users[username] = {
        "username": username, "email": username, "name": data.name or username,
        "password": pwd_ctx.hash(data.password), "role": "user",
        "created_at": datetime.utcnow().isoformat()
    }
    write_json(USERS_FILE, users)
    gh_write_json("data/users.json", USERS_FILE, users)
    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(username, {})
    write_json(DEVICES_FILE, devices)
    gh_write_json("data/devices.json", DEVICES_FILE, devices)
    return {"ok": True, "msg": "Usuario creado"}
 
@app.post("/login")
def login(data: LoginModel):
    username = (data.username or data.email).strip()
    password = data.password
    if username == ADMIN_USER and password == ADMIN_PASS:
        token = create_token(ADMIN_USER, "admin")
        return {"ok": True, "token": token, "role": "admin",
                "username": ADMIN_USER, "email": ADMIN_USER,
                "user": {"username": ADMIN_USER, "email": ADMIN_USER, "role": "admin"}}
    users = read_json(USERS_FILE, {})
    user  = users.get(username)
    if not user:
        for u in users.values():
            if u.get("email","").lower() == username.lower():
                user = u; username = u["username"]; break
    if not user: raise HTTPException(401, "Usuario no encontrado")
    try:    ok = pwd_ctx.verify(password, user["password"])
    except: ok = False
    if not ok: raise HTTPException(401, "Contrasena incorrecta")
    role = user.get("role","user")
    return {"ok": True, "token": create_token(username, role), "role": role,
            "username": username, "email": username,
            "user": {"username": username, "email": username, "role": role}}
 
@app.get("/me")
def me(user=Depends(get_user)): return user
 
# ── Admin usuarios ─────────────────────────────────────────────────────
@app.get("/admin/users")
def admin_users(admin=Depends(require_admin)):
    users = read_json(USERS_FILE, {})
    return [{"username": k, "email": v.get("email",k), "role": v.get("role","user"),
             "created_at": v.get("created_at","")} for k,v in users.items()]
 
@app.post("/admin/users")
def admin_create_user(data: UserCreateModel, admin=Depends(require_admin)):
    users    = read_json(USERS_FILE, {})
    username = (data.username or data.email).strip()
    if not username: raise HTTPException(400, "Usuario requerido")
    if username in users: raise HTTPException(400, "Usuario ya existe")
    role = data.role if data.role in ["admin","user"] else "user"
    users[username] = {
        "username": username, "email": username,
        "password": pwd_ctx.hash(data.password), "role": role,
        "created_at": datetime.utcnow().isoformat()
    }
    write_json(USERS_FILE, users)
    gh_write_json("data/users.json", USERS_FILE, users)
 
    # Equipos asignados al crear. Sin esto el usuario entra y no ve NADA,
    # porque quedaba registrado con la lista de equipos vacia.
    devices  = read_json(DEVICES_FILE, {})
    catalogo = {}
    for asignados in devices.values():
        if isinstance(asignados, dict): catalogo.update(asignados)
    propios = {}
    for did in (data.devices or []):
        did = str(did).strip()
        if not did: continue
        propios[did] = catalogo.get(did, {"nombre": did, "icono": "antenna", "color": "#00c8ff"})
    devices[username] = propios
    write_json(DEVICES_FILE, devices)
    # Persistir tambien en GitHub: el disco de Render es efimero y sin esto
    # las asignaciones se perdian en cada reinicio.
    gh_write_json("data/devices.json", DEVICES_FILE, devices)
    return {"ok": True, "msg": "Usuario creado", "devices": list(propios.keys())}
 
@app.delete("/admin/users/{username}")
def admin_delete_user(username: str, admin=Depends(require_admin)):
    if username == ADMIN_USER: raise HTTPException(400, "No se puede eliminar el admin")
    users   = read_json(USERS_FILE, {})
    devices = read_json(DEVICES_FILE, {})
    if username in users:
        del users[username]; write_json(USERS_FILE, users)
        gh_write_json("data/users.json", USERS_FILE, users)
    if username in devices:
        del devices[username]; write_json(DEVICES_FILE, devices)
        gh_write_json("data/devices.json", DEVICES_FILE, devices)
    return {"ok": True}
 
# ── Dispositivos ───────────────────────────────────────────────────────
@app.post("/devices")
def add_device(data: DeviceModel, user=Depends(get_user)):
    devices   = read_json(DEVICES_FILE, {})
    device_id = (data.device_id or data.device).strip()
    nombre    = data.nombre if data.nombre != "Sin nombre" else (data.name or device_id)
    if not device_id: raise HTTPException(400, "device_id requerido")
    owner = data.owner if user["role"]=="admin" and data.owner else user["username"]
    devices.setdefault(owner, {})
    devices[owner][device_id] = {
        "device_id": device_id, "device": device_id, "nombre": nombre, "name": nombre,
        "icono": data.icono or "antenna", "color": data.color or "#00c8ff",
        "owner": owner, "created_at": datetime.utcnow().isoformat()
    }
    write_json(DEVICES_FILE, devices)
    gh_write_json("data/devices.json", DEVICES_FILE, devices)
    return {"ok": True, "device": devices[owner][device_id]}
 
@app.post("/admin/device")
def admin_add_device(data: DeviceModel, admin=Depends(require_admin)):
    data.owner = data.owner or ADMIN_USER
    return add_device(data, admin)
 
@app.post("/admin/assign")
def admin_assign(data: AssignModel, admin=Depends(require_admin)):
    devices = read_json(DEVICES_FILE, {})
    users   = read_json(USERS_FILE, {})
    target  = None
    for k,u in users.items():
        if k == data.user_email or u.get("email","") == data.user_email:
            target = k; break
    if not target: raise HTTPException(404, "Usuario no existe")
    found = None; old_owner = None
    for owner, devs in devices.items():
        if data.device in devs: found = devs[data.device]; old_owner = owner; break
    if not found:
        found = {"device_id": data.device, "device": data.device,
                 "nombre": data.device, "name": data.device,
                 "icono": "antenna", "color": "#00c8ff",
                 "created_at": datetime.utcnow().isoformat()}
    found["owner"] = target
    devices.setdefault(target, {})
    devices[target][data.device] = found
    if old_owner and old_owner != target:
        del devices[old_owner][data.device]
    write_json(DEVICES_FILE, devices)
    gh_write_json("data/devices.json", DEVICES_FILE, devices)
    return {"ok": True, "msg": "Equipo asignado"}
 
@app.get("/devices")
def list_devices(user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    if user["role"] == "admin":
        result = []
        for owner, devs in devices.items():
            for d in devs.values():
                d["owner"] = owner; result.append(d)
        return result
    return list(devices.get(user["username"], {}).values())
 
@app.put("/devices/{device_id}")
def update_device(device_id: str, data: DeviceModel, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    nombre  = data.nombre if data.nombre != "Sin nombre" else (data.name or device_id)
    if user["role"] == "admin":
        for owner in list(devices.keys()):
            if device_id in devices[owner]:
                new_owner = data.owner if data.owner else owner
                dev = devices[owner][device_id]
                dev.update({"nombre": nombre, "name": nombre, "icono": data.icono,
                            "color": data.color, "owner": new_owner,
                            "updated_at": datetime.utcnow().isoformat()})
                if new_owner != owner:
                    devices.setdefault(new_owner, {})
                    devices[new_owner][device_id] = dev
                    del devices[owner][device_id]
                write_json(DEVICES_FILE, devices)
                gh_write_json("data/devices.json", DEVICES_FILE, devices)
                return {"ok": True, "device": dev}
    owner = user["username"]
    if owner in devices and device_id in devices[owner]:
        devices[owner][device_id].update({"nombre": nombre, "name": nombre,
            "icono": data.icono, "color": data.color,
            "updated_at": datetime.utcnow().isoformat()})
        write_json(DEVICES_FILE, devices)
        gh_write_json("data/devices.json", DEVICES_FILE, devices)
        return {"ok": True, "device": devices[owner][device_id]}
    raise HTTPException(404, "Dispositivo no encontrado")
 
@app.delete("/devices/{device_id}")
def delete_device(device_id: str, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    if user["role"] == "admin":
        for owner in list(devices.keys()):
            if device_id in devices[owner]:
                del devices[owner][device_id]; write_json(DEVICES_FILE, devices)
                gh_write_json("data/devices.json", DEVICES_FILE, devices)
                return {"ok": True}
    owner = user["username"]
    if owner in devices and device_id in devices[owner]:
        del devices[owner][device_id]; write_json(DEVICES_FILE, devices)
        gh_write_json("data/devices.json", DEVICES_FILE, devices)
        return {"ok": True}
    raise HTTPException(404, "Dispositivo no encontrado")
 
# ── Device status — ESP32 → Backend ────────────────────────────────────
@app.post("/device-status")
async def device_status_post(request: Request):
    check_device_key(request)
    data = await request.json()
 
    device      = data.get("device",     "HERMES-01")
    estado      = data.get("estado",     "SIN ESTADO")
    despertar   = data.get("despertar",  data.get("wake",   0))
    ciclo_min   = data.get("ciclo_min",  data.get("ciclo",  0))
    fallos_gps  = data.get("fallos_gps", data.get("fallos", 0))
    lat         = float(data.get("lat",  0) or 0)
    lon         = float(data.get("lon",  0) or 0)
    fecha       = data.get("fecha",  "")
    hora        = data.get("hora",   "")
    bateria_v   = data.get("bateria_v",   data.get("bat_v",  0))
    bateria_pct = data.get("bateria_pct", data.get("bat_pct",0))
    wifi        = data.get("wifi", "conectado")
    now         = datetime.utcnow().isoformat()
 
    fw_version = data.get("fw_version", "")
 
    # Respaldo de marca temporal: si el equipo no logró leer fecha/hora del
    # satélite, se derivan de la hora del servidor (UTC-5 Colombia) en lugar de
    # guardar "No disponible", que dejaba huecos en el historial y la ruta.
    if (not fecha) or (not hora) or hora == "No disponible":
        _col = datetime.utcnow() - timedelta(hours=5)
        if not fecha:
            fecha = _col.strftime("%d/%m/%Y")
        if (not hora) or hora == "No disponible":
            hora = _col.strftime("%H:%M:%S")
 
    row = {"device": device, "estado": estado, "despertar": despertar,
           "ciclo_min": ciclo_min, "fallos_gps": fallos_gps,
           "lat": lat, "lon": lon, "fecha": fecha, "hora": hora,
           "bateria_v": bateria_v, "bateria_pct": bateria_pct,
           "wifi": wifi, "fw_version": fw_version, "created_at": now}
 
    with _gh_lock:
        # 1. Status local + GitHub
        all_status = read_json(STATUS_FILE, {})
        all_status[device] = row
        write_json(STATUS_FILE, all_status)
        gh_write_json("static/files/status.json", STATUS_FILE, all_status)
 
        # 2. History local + GitHub (solo si tiene coordenadas válidas)
        history = read_json(HISTORY_FILE, [])
        history.append(row)
        if len(history) > 50000:
            history = history[-50000:]
        write_json(HISTORY_FILE, history)
        # GitHub history: async para no bloquear la respuesta al ESP32
        if USE_GITHUB:
            content = json.dumps(history, indent=2, ensure_ascii=False)
            t = threading.Thread(target=gh_put_file,
                args=("data/history.json", content, f"GPS {device} {fecha} {hora}"),
                daemon=True)
            t.start()
 
        # 3. CSV append local
        with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([len(history), despertar, fecha, hora,
                                     lat, lon, estado, bateria_v, bateria_pct, device, now])
 
        # 4. Sincronizar CSV completo a GitHub cada 10 puntos
        if USE_GITHUB and len(history) % 10 == 0:
            try:
                with open(CSV_PATH, "r", encoding="utf-8") as f:
                    csv_content = f.read()
                t2 = threading.Thread(target=gh_put_file,
                    args=("static/files/gps_log.csv", csv_content, "CSV update"),
                    daemon=True)
                t2.start()
            except: pass
 
    return {"ok": True, "status": row}
 
@app.get("/device-status")
def device_status_get(device: str = "HERMES-01"):
    return read_json(STATUS_FILE, {}).get(device, {})
 
@app.get("/status")
def get_all_status(): return read_json(STATUS_FILE, {})
 
@app.get("/status/{device_id}")
def get_status(device_id: str):
    s = read_json(STATUS_FILE, {})
    if device_id not in s: raise HTTPException(404, "Dispositivo no encontrado")
    return s[device_id]
 
# ── Historial ──────────────────────────────────────────────────────────
@app.get("/history")
def get_history(device: str = None, start: str = None, end: str = None):
    result = []
    for h in read_json(HISTORY_FILE, []):
        if device and h.get("device") != device: continue
        # Se filtra por la hora REAL de captura (no por la de llegada), para que
        # un reenvio pendiente aparezca en el dia en que se capturo.
        if not in_range(capture_dt(h).isoformat(), start, end): continue
        if not valid_point(h): continue
        result.append(h)
    # Orden cronologico real: sin esto los reenvios quedaban al final del
    # recorrido y la ruta dibujaba saltos hacia atras (distancia inflada).
    result.sort(key=capture_dt)
    return result
 
@app.get("/latest/{device_id}")
def latest(device_id: str):
    hist = [h for h in read_json(HISTORY_FILE,[])
            if h.get("device")==device_id and valid_point(h)]
    if not hist: raise HTTPException(404, "Sin ubicacion")
    # El mas reciente por hora de CAPTURA. Usar el ultimo insertado devolvia
    # una posicion antigua cuando acababa de llegar un reenvio pendiente.
    return max(hist, key=capture_dt)
 
@app.get("/fleet/latest")
def fleet_latest(devices: str = None):
    status = read_json(STATUS_FILE, {})
    if not devices: return status
    selected = [d.strip() for d in devices.split(",") if d.strip()]
    return {d: status.get(d) for d in selected if d in status}
 
# ── Comandos ────────────────────────────────────────────────────────────
@app.post("/command")
def set_command(data: CommandModel):
    write_command(data.device or "HERMES-01", data.cmd.strip())
    return {"ok": True, "device": data.device, "cmd": data.cmd,
            "msg": f"Comando guardado para {data.device}. Se aplica en el proximo despertar."}
 
@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = False):
    entry = get_cmd_for_device(device)
    cmd   = entry.get("cmd","none")
    if clear and cmd != "none":
        cmds = read_commands()
        if device in cmds:
            attempts = cmds[device].get("attempts",0) + 1
            # update/reset son de un solo disparo: se auto-confirman por Telegram
            # y por el reinicio del ESP32, así que se limpian en la PRIMERA lectura
            # para evitar doble flasheo / doble reinicio. Los comandos de ciclo
            # conservan el reintento (attempts>=2) por si la 1a peticion se pierde.
            one_shot = cmd in ("update", "reset")
            if one_shot or attempts >= 2:
                cmds[device]["cmd"] = "none"
                cmds[device]["executed_at"] = datetime.utcnow().isoformat()
            cmds[device]["attempts"] = attempts
            write_json(COMMAND_FILE, cmds)
            if USE_GITHUB:
                t = threading.Thread(target=gh_put_file,
                    args=("static/files/command.json", json.dumps(cmds,indent=2)), daemon=True)
                t.start()
    return {"device": device, "cmd": cmd, "created_at": entry.get("created_at","")}
 
@app.get("/command/status")
def command_status(user=Depends(get_user)): return read_commands()
 
@app.delete("/command/{device}")
def clear_device_command(device: str, user=Depends(get_user)):
    cmds = read_commands()
    if device in cmds: cmds[device]["cmd"] = "none"; write_json(COMMAND_FILE, cmds)
    return {"ok": True}
 
# ── CSV ─────────────────────────────────────────────────────────────────
@app.get("/files/gps_log.csv")
def download_csv(device: str = None, start: str = None, end: str = None):
    if device or start or end:
        rows = get_history(device=device, start=start, end=end)
        if not rows: raise HTTPException(404, "Sin datos en el rango seleccionado")
        lines = ["id,despertar,fecha,hora,lat,lon,estado,bateria_v,bateria_pct,device,created_at"]
        for i,r in enumerate(rows,1):
            lines.append(",".join([
                str(i), str(r.get("despertar","")), str(r.get("fecha","")),
                str(r.get("hora","")), str(r.get("lat","")), str(r.get("lon","")),
                str(r.get("estado","")), str(r.get("bateria_v","")),
                str(r.get("bateria_pct","")), str(r.get("device","")),
                str(r.get("created_at",""))
            ]))
        content = "\n".join(lines)
        d_tag = (start or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
        fname = f"hermes_{device or 'todos'}_{d_tag}.csv"
        return Response(content, media_type="text/csv",
                       headers={"Content-Disposition": f"attachment; filename={fname}",
                                "Access-Control-Allow-Origin": "*"})
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH,"w",encoding="utf-8",newline="") as f:
            csv.writer(f).writerow(["id","despertar","fecha","hora","lat","lon",
                                    "estado","bateria_v","bateria_pct","device","created_at"])
    return FileResponse(CSV_PATH, media_type="text/csv", filename="gps_log.csv",
                       headers={"Access-Control-Allow-Origin":"*","Cache-Control":"no-cache"})
 
@app.get("/csv")
def csv_alt(device: str = None, start: str = None, end: str = None):
    return download_csv(device=device, start=start, end=end)
 
# ── KML ─────────────────────────────────────────────────────────────────
@app.get("/files/ruta.kml")
def generar_kml(device: str = None, start: str = None, end: str = None):
    rows = get_history(device=device, start=start, end=end)
    if not rows: raise HTTPException(404, "No hay puntos GPS en el rango seleccionado")
 
    coords_line = ""
    placemarks  = ""
    count = 0
    for i,p in enumerate(rows):
        try:
            lat = float(p.get("lat",0) or 0)
            lon = float(p.get("lon",0) or 0)
        except: continue
        if abs(lat)<0.0001 or abs(lon)<0.0001: continue
        count += 1
        coords_line += f"            {lon},{lat},0\n"
        dev  = p.get("device","HERMES")
        bat  = p.get("bateria_pct","--")
        est  = p.get("estado","--")
        fech = p.get("fecha",""); hor = p.get("hora","")
        placemarks += f"""
    <Placemark>
      <name>#{count} {dev}</name>
      <description>{fech} {hor} | Estado: {est} | Bat: {bat}%</description>
      <styleUrl>#pointStyle</styleUrl>
      <Point><coordinates>{lon},{lat},0</coordinates></Point>
    </Placemark>"""
 
    if not coords_line:
        raise HTTPException(404, "Sin coordenadas GPS validas en el rango")
 
    dev_name = device or "HERMES"
    d_tag    = (start or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
    d_tag2   = (end   or "")[:10] or datetime.utcnow().strftime("%Y-%m-%d")
 
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Ruta {dev_name} — {d_tag} al {d_tag2}</name>
  <description>{count} puntos GPS</description>
  <Style id="lineStyle">
    <LineStyle><color>ff00c8ff</color><width>4</width></LineStyle>
    <PolyStyle><color>4400c8ff</color></PolyStyle>
  </Style>
  <Style id="pointStyle">
    <IconStyle>
      <color>ff00ff88</color><scale>0.7</scale>
      <Icon><href>http://maps.google.com/mapfiles/kml/paddle/grn-circle.png</href></Icon>
    </IconStyle>
  </Style>
  <Placemark>
    <name>Recorrido {dev_name}</name>
    <styleUrl>#lineStyle</styleUrl>
    <LineString>
      <tessellate>1</tessellate>
      <coordinates>
{coords_line}
      </coordinates>
    </LineString>
  </Placemark>
{placemarks}
</Document>
</kml>'''
 
    with open(KML_PATH,"w",encoding="utf-8") as f: f.write(kml)
    fname = f"ruta_{dev_name}_{d_tag}.kml"
    return FileResponse(KML_PATH,
        media_type="application/vnd.google-earth.kml+xml", filename=fname,
        headers={"Access-Control-Allow-Origin":"*","Cache-Control":"no-cache"})
 
@app.get("/export/kml")
def export_kml(device: str = None, start: str = None, end: str = None):
    return generar_kml(device=device, start=start, end=end)
 
# ══════════════════════════════════════════════════════════════════════
#  OTA — Actualización remota de firmware
# ══════════════════════════════════════════════════════════════════════
import shutil
 
FIRMWARE_DIR  = os.path.join(STATIC_DIR, "firmware")
FIRMWARE_PATH = os.path.join(FIRMWARE_DIR, "hermes.bin")
FIRMWARE_VER  = os.path.join(FIRMWARE_DIR, "version.txt")
 
os.makedirs(FIRMWARE_DIR, exist_ok=True)
 
@app.get("/firmware/hermes.bin")
def download_firmware():
    """ESP32 descarga el firmware actualizado."""
    if not os.path.exists(FIRMWARE_PATH):
        raise HTTPException(404, "Sin firmware disponible — sube un .bin desde el panel Admin")
    return FileResponse(FIRMWARE_PATH,
        media_type="application/octet-stream",
        filename="hermes.bin",
        headers={"Cache-Control": "no-cache"})
 
@app.get("/firmware/version")
def get_firmware_version():
    """Retorna la versión del firmware disponible."""
    if not os.path.exists(FIRMWARE_VER):
        return {"version": None, "available": False}
    with open(FIRMWARE_VER) as f:
        ver = f.read().strip()
    size = os.path.getsize(FIRMWARE_PATH) if os.path.exists(FIRMWARE_PATH) else 0
    return {"version": ver, "available": True, "size_kb": round(size/1024, 1)}
 
@app.post("/firmware/upload")
async def upload_firmware(request: Request, admin=Depends(require_admin)):
    """Admin sube nuevo .bin desde la webapp."""
    try:
        body = await request.body()
        if len(body) < 1000:
            raise HTTPException(400, "Archivo muy pequeño — no parece un firmware válido")
        if len(body) > 4_000_000:
            raise HTTPException(400, "Archivo muy grande — máximo 4MB")
 
        # Guardar .bin
        with open(FIRMWARE_PATH, "wb") as f:
            f.write(body)
 
        # Guardar versión desde header
        version = request.headers.get("X-Firmware-Version", "unknown")
        with open(FIRMWARE_VER, "w") as f:
            f.write(version)
 
        size_kb = round(len(body) / 1024, 1)
        print(f"[OTA] Firmware subido: {size_kb} KB v{version}", flush=True)
 
        # Subir a GitHub también
        if USE_GITHUB:
            import base64
            encoded = base64.b64encode(body).decode("utf-8")
            t = threading.Thread(target=gh_put_file,
                args=(f"static/firmware/hermes.bin", encoded,
                      f"OTA firmware v{version}"), daemon=True)
            t.start()
 
        return {"ok": True, "size_kb": size_kb, "version": version,
                "msg": f"Firmware v{version} ({size_kb} KB) subido correctamente"}
 
    except HTTPException: raise
    except Exception as e:
        raise HTTPException(500, f"Error subiendo firmware: {str(e)}")
 
@app.delete("/firmware")
def delete_firmware(admin=Depends(require_admin)):
    """Eliminar firmware disponible."""
    if os.path.exists(FIRMWARE_PATH):
        os.remove(FIRMWARE_PATH)
    if os.path.exists(FIRMWARE_VER):
        os.remove(FIRMWARE_VER)
    return {"ok": True, "msg": "Firmware eliminado"}

