import os
import json
import csv
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext

BASE_URL    = os.getenv("BASE_URL",    "https://gps-backend-pqzg.onrender.com")
SECRET      = os.getenv("SECRET",      "HERMES_SECRET_2025")
DEVICE_KEY  = os.getenv("DEVICE_KEY",  "HERMES_DEVICE_KEY_123")

# ── Credenciales admin (se pueden cambiar con variables de entorno) ──
ADMIN_USER  = os.getenv("ADMIN_USER",  "Hermesadmin")
ADMIN_PASS  = os.getenv("ADMIN_PASS",  "Colombia2026*")

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

app = FastAPI(title="HERMES GPS Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/files",  StaticFiles(directory=FILES_DIR),  name="files")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

pwd_ctx  = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


# ── Helpers JSON ──────────────────────────────────────────────────────
def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Inicializar archivos ──────────────────────────────────────────────
def init_files():
    for path, default in [
        (USERS_FILE,   {}),
        (DEVICES_FILE, {}),
        (HISTORY_FILE, []),
        (STATUS_FILE,  {}),
    ]:
        if not os.path.exists(path):
            write_json(path, default)

    if not os.path.exists(COMMAND_FILE):
        write_json(COMMAND_FILE, {"cmd": "none"})

    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([
                "id","despertar","fecha","hora","lat","lon",
                "estado","bateria_v","bateria_pct","device","created_at"
            ])

init_files()

# ── Garantizar usuario admin ──────────────────────────────────────────
def ensure_admin():
    users = read_json(USERS_FILE, {})
    users[ADMIN_USER] = {
        "username":   ADMIN_USER,
        "email":      ADMIN_USER,
        "name":       "Administrador HERMES",
        "password":   pwd_ctx.hash(ADMIN_PASS),
        "role":       "admin",
        "created_at": users.get(ADMIN_USER, {}).get("created_at", datetime.utcnow().isoformat()),
        "updated_at": datetime.utcnow().isoformat(),
    }
    write_json(USERS_FILE, users)

ensure_admin()


# ── JWT ───────────────────────────────────────────────────────────────
def create_token(username: str, role: str) -> str:
    payload = {"sub": username, "role": role,
                "exp": datetime.utcnow() + timedelta(days=30)}
    return jwt.encode(payload, SECRET, algorithm="HS256")

def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token requerido")
    try:
        payload  = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        username = payload.get("sub")
        role     = payload.get("role", "user")
        if not username:
            raise HTTPException(status_code=401, detail="Token invalido")
        return {"username": username, "email": username, "role": role}
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalido")

def require_admin(user=Depends(get_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo administrador")
    return user

def check_device_key(request: Request):
    key = request.headers.get("x-device-key")
    if key != DEVICE_KEY:
        raise HTTPException(status_code=401, detail="Device key invalida")


# ── Helpers ───────────────────────────────────────────────────────────
def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except Exception:
        return None

def in_range(created_at, start, end):
    dt = parse_dt(created_at)
    s  = parse_dt(start)
    e  = parse_dt(end)
    if not dt:  return True
    if s and dt < s: return False
    if e and dt > e: return False
    return True

def valid_point(p):
    try:
        return float(p.get("lat",0)) != 0 and float(p.get("lon",0)) != 0
    except Exception:
        return False


# ── Modelos ───────────────────────────────────────────────────────────
class RegisterModel(BaseModel):
    username: str = ""
    email:    str = ""
    name:     str = ""
    password: str

class LoginModel(BaseModel):
    username: str = ""
    email:    str = ""
    password: str

class UserCreateModel(BaseModel):
    username: str = ""
    email:    str = ""
    password: str
    role:     str = "user"

class DeviceModel(BaseModel):
    device_id: str = ""
    device:    str = ""
    nombre:    str = "Sin nombre"
    name:      str = ""
    icono:     str = "antenna"
    color:     str = "#00c8ff"
    owner:     str = ""

class AssignModel(BaseModel):
    user_email: str
    device:     str

class CommandModel(BaseModel):
    cmd:    str
    device: str = "HERMES-01"


# ── Rutas publicas ────────────────────────────────────────────────────
@app.get("/")
def home():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"ok": True, "msg": "Backend HERMES activo"}

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat(), "admin": ADMIN_USER}

@app.get("/api")
def api_info():
    return {"name": "HERMES GPS Backend", "status": "online",
            "csv": f"{BASE_URL}/files/gps_log.csv",
            "kml": f"{BASE_URL}/files/ruta.kml",
            "health": f"{BASE_URL}/health"}


# ── Auth ──────────────────────────────────────────────────────────────
@app.post("/register")
def register(data: RegisterModel):
    users    = read_json(USERS_FILE, {})
    # acepta email o username como identificador
    username = (data.username or data.email).strip()
    if not username:
        raise HTTPException(status_code=400, detail="Usuario requerido")
    if username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    users[username] = {
        "username":   username,
        "email":      username,
        "name":       data.name or username,
        "password":   pwd_ctx.hash(data.password),
        "role":       "user",
        "created_at": datetime.utcnow().isoformat(),
    }
    write_json(USERS_FILE, users)
    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(username, {})
    write_json(DEVICES_FILE, devices)
    return {"ok": True, "msg": "Usuario creado"}

@app.post("/login")
def login(data: LoginModel):
    # el frontend puede enviar el valor en "username" o "email"
    username = (data.username or data.email).strip()
    password = data.password

    # ── login directo para el admin (sin hash, por si cambia la pass) ──
    if username == ADMIN_USER and password == ADMIN_PASS:
        token = create_token(ADMIN_USER, "admin")
        return {"ok": True, "token": token, "role": "admin",
                "username": ADMIN_USER, "email": ADMIN_USER,
                "user": {"username": ADMIN_USER, "email": ADMIN_USER, "role": "admin"}}

    users = read_json(USERS_FILE, {})
    user  = users.get(username)

    # si no encontro por username, intentar buscar por email
    if not user:
        for u in users.values():
            if u.get("email","").lower() == username.lower():
                user = u
                username = u["username"]
                break

    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")

    try:
        ok = pwd_ctx.verify(password, user["password"])
    except Exception:
        ok = False

    if not ok:
        raise HTTPException(status_code=401, detail="Contrasena incorrecta")

    role  = user.get("role", "user")
    token = create_token(username, role)
    return {"ok": True, "token": token, "role": role,
            "username": username, "email": username,
            "user": {"username": username, "email": username, "role": role}}

@app.get("/me")
def me(user=Depends(get_user)):
    return user


# ── Admin usuarios ────────────────────────────────────────────────────
@app.get("/admin/users")
def admin_users(admin=Depends(require_admin)):
    users = read_json(USERS_FILE, {})
    return [{"username": k, "email": v.get("email", k),
             "role": v.get("role","user"), "created_at": v.get("created_at","")}
            for k, v in users.items()]

@app.post("/admin/users")
def admin_create_user(data: UserCreateModel, admin=Depends(require_admin)):
    users    = read_json(USERS_FILE, {})
    username = (data.username or data.email).strip()
    if not username:
        raise HTTPException(status_code=400, detail="Usuario requerido")
    if username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    role = data.role if data.role in ["admin","user"] else "user"
    users[username] = {"username": username, "email": username,
                       "password": pwd_ctx.hash(data.password),
                       "role": role, "created_at": datetime.utcnow().isoformat()}
    write_json(USERS_FILE, users)
    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(username, {})
    write_json(DEVICES_FILE, devices)
    return {"ok": True, "msg": "Usuario creado"}

@app.delete("/admin/users/{username}")
def admin_delete_user(username: str, admin=Depends(require_admin)):
    if username == ADMIN_USER:
        raise HTTPException(status_code=400, detail="No se puede eliminar el admin principal")
    users   = read_json(USERS_FILE, {})
    devices = read_json(DEVICES_FILE, {})
    if username in users:   del users[username];   write_json(USERS_FILE, users)
    if username in devices: del devices[username]; write_json(DEVICES_FILE, devices)
    return {"ok": True}


# ── Dispositivos ──────────────────────────────────────────────────────
@app.post("/devices")
def add_device(data: DeviceModel, user=Depends(get_user)):
    devices   = read_json(DEVICES_FILE, {})
    device_id = (data.device_id or data.device).strip()
    nombre    = data.nombre if data.nombre != "Sin nombre" else (data.name or device_id)
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id requerido")
    owner = data.owner if user["role"]=="admin" and data.owner else user["username"]
    devices.setdefault(owner, {})
    devices[owner][device_id] = {
        "device_id": device_id, "device": device_id,
        "nombre": nombre, "name": nombre,
        "icono": data.icono or "antenna", "color": data.color or "#00c8ff",
        "owner": owner, "created_at": datetime.utcnow().isoformat(),
    }
    write_json(DEVICES_FILE, devices)
    return {"ok": True, "device": devices[owner][device_id]}

@app.post("/admin/device")
def admin_add_device(data: DeviceModel, admin=Depends(require_admin)):
    data.owner = data.owner or ADMIN_USER
    return add_device(data, admin)

@app.post("/admin/assign")
def admin_assign(data: AssignModel, admin=Depends(require_admin)):
    devices = read_json(DEVICES_FILE, {})
    users   = read_json(USERS_FILE, {})

    # buscar el usuario por username o email
    target = None
    for k, u in users.items():
        if k == data.user_email or u.get("email","") == data.user_email:
            target = k; break
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no existe")

    found = None; old_owner = None
    for owner, devs in devices.items():
        if data.device in devs:
            found = devs[data.device]; old_owner = owner; break
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
                dev       = devices[owner][device_id]
                dev.update({"nombre": nombre, "name": nombre,
                            "icono": data.icono, "color": data.color,
                            "owner": new_owner, "updated_at": datetime.utcnow().isoformat()})
                if new_owner != owner:
                    devices.setdefault(new_owner, {})
                    devices[new_owner][device_id] = dev
                    del devices[owner][device_id]
                write_json(DEVICES_FILE, devices)
                return {"ok": True, "device": dev}
    owner = user["username"]
    if owner in devices and device_id in devices[owner]:
        devices[owner][device_id].update({"nombre": nombre, "name": nombre,
            "icono": data.icono, "color": data.color,
            "updated_at": datetime.utcnow().isoformat()})
        write_json(DEVICES_FILE, devices)
        return {"ok": True, "device": devices[owner][device_id]}
    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

@app.delete("/devices/{device_id}")
def delete_device(device_id: str, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    if user["role"] == "admin":
        for owner in list(devices.keys()):
            if device_id in devices[owner]:
                del devices[owner][device_id]; write_json(DEVICES_FILE, devices)
                return {"ok": True}
    owner = user["username"]
    if owner in devices and device_id in devices[owner]:
        del devices[owner][device_id]; write_json(DEVICES_FILE, devices)
        return {"ok": True}
    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")


# ── Device status (ESP32 -> Backend) ─────────────────────────────────
@app.post("/device-status")
async def device_status_post(request: Request):
    check_device_key(request)
    data = await request.json()

    device      = data.get("device",      "HERMES-01")
    estado      = data.get("estado",      "SIN ESTADO")
    despertar   = data.get("despertar",   data.get("wake",   0))
    ciclo_min   = data.get("ciclo_min",   data.get("ciclo",  0))
    fallos_gps  = data.get("fallos_gps",  data.get("fallos", 0))
    lat         = float(data.get("lat",   0) or 0)
    lon         = float(data.get("lon",   0) or 0)
    fecha       = data.get("fecha",  "")
    hora        = data.get("hora",   "")
    bateria_v   = data.get("bateria_v",   data.get("bat_v",  0))
    bateria_pct = data.get("bateria_pct", data.get("bat_pct",0))
    wifi        = data.get("wifi", "conectado")
    now         = datetime.utcnow().isoformat()

    status = {"device": device, "estado": estado, "despertar": despertar,
              "ciclo_min": ciclo_min, "fallos_gps": fallos_gps,
              "lat": lat, "lon": lon, "fecha": fecha, "hora": hora,
              "bateria_v": bateria_v, "bateria_pct": bateria_pct,
              "wifi": wifi, "created_at": now}

    all_status = read_json(STATUS_FILE, {}); all_status[device] = status
    write_json(STATUS_FILE, all_status)

    history = read_json(HISTORY_FILE, []); history.append(status)
    write_json(HISTORY_FILE, history)

    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([len(history), despertar, fecha, hora, lat, lon,
                                 estado, bateria_v, bateria_pct, device, now])
    return {"ok": True, "status": status}

@app.get("/device-status")
def device_status_get(device: str = "HERMES-01"):
    return read_json(STATUS_FILE, {}).get(device, {})

@app.get("/status")
def get_all_status():
    return read_json(STATUS_FILE, {})

@app.get("/status/{device_id}")
def get_status(device_id: str):
    s = read_json(STATUS_FILE, {})
    if device_id not in s:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    return s[device_id]


# ── Historial / rutas ────────────────────────────────────────────────
@app.get("/latest/{device_id}")
def latest(device_id: str):
    history = [h for h in read_json(HISTORY_FILE,[]) if h.get("device")==device_id and valid_point(h)]
    if not history:
        raise HTTPException(status_code=404, detail="Sin ubicacion")
    return history[-1]

@app.get("/fleet/latest")
def fleet_latest(devices: str = None):
    status = read_json(STATUS_FILE, {})
    if not devices: return status
    selected = [d.strip() for d in devices.split(",") if d.strip()]
    return {d: status.get(d) for d in selected if d in status}

@app.get("/history")
def history(device: str = None, start: str = None, end: str = None):
    result = []
    for h in read_json(HISTORY_FILE, []):
        if device and h.get("device") != device: continue
        if not in_range(h.get("created_at",""), start, end): continue
        if not valid_point(h): continue
        result.append(h)
    return result


# ── Comandos ────────────────────────────────────────────────────────
@app.post("/command")
def set_command(data: CommandModel):
    write_json(COMMAND_FILE, {"device": data.device, "cmd": data.cmd,
                               "created_at": datetime.utcnow().isoformat()})
    return {"ok": True, "cmd": data.cmd}

@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = False):
    cmd = read_json(COMMAND_FILE, {"cmd": "none"})
    if clear: write_json(COMMAND_FILE, {"cmd": "none"})
    return cmd


# ── Archivos ─────────────────────────────────────────────────────────
@app.get("/files/gps_log.csv")
def download_csv():
    if not os.path.exists(CSV_PATH):
        raise HTTPException(status_code=404, detail="gps_log.csv no encontrado")
    return FileResponse(CSV_PATH, media_type="text/csv", filename="gps_log.csv")

@app.get("/files/ruta.kml")
def generar_kml(device: str = None, start: str = None, end: str = None):
    data = history(device=device, start=start, end=end)
    if not data:
        raise HTTPException(status_code=404, detail="No hay puntos GPS validos")
    coords = ""
    for p in data:
        lat = float(p.get("lat",0)); lon = float(p.get("lon",0))
        if lat and lon: coords += f"{lon},{lat},0\n"
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document><name>Ruta HERMES</name>
<Placemark><name>Recorrido GPS</name>
<Style><LineStyle><color>ff0000ff</color><width>4</width></LineStyle></Style>
<LineString><tessellate>1</tessellate><coordinates>
{coords}
</coordinates></LineString></Placemark>
</Document></kml>'''
    with open(KML_PATH, "w", encoding="utf-8") as f: f.write(kml)
    return FileResponse(KML_PATH, media_type="application/vnd.google-earth.kml+xml", filename="ruta.kml")

@app.get("/export/kml")
def export_kml(device: str = None, start: str = None, end: str = None):
    return generar_kml(device=device, start=start, end=end)
