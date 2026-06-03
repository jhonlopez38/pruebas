import os
import json
import csv
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel

BASE_URL = os.getenv("BASE_URL", "https://gps-backend-pqzg.onrender.com")
SECRET = os.getenv("SECRET", "HERMES_SECRET_2025")
DEVICE_KEY = os.getenv("DEVICE_KEY", "HERMES_DEVICE_KEY_123")

ADMIN_USER = os.getenv("ADMIN_USER", "Hermesadmin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Colombia2026*")

STATIC_DIR = "static"
FILES_DIR = "static/files"
DATA_DIR = "data"

CSV_PATH = os.path.join(FILES_DIR, "gps_log.csv")
KML_PATH = os.path.join(FILES_DIR, "ruta.kml")
COMMAND_FILE = os.path.join(FILES_DIR, "command.json")
STATUS_FILE = os.path.join(FILES_DIR, "status.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="HERMES GPS Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/files", StaticFiles(directory=FILES_DIR), name="files")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


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


def init_files():
    for path, default in [
        (USERS_FILE, {}),
        (DEVICES_FILE, {}),
        (HISTORY_FILE, []),
        (STATUS_FILE, {}),
        (COMMAND_FILE, {"cmd": "none"}),
    ]:
        if not os.path.exists(path):
            write_json(path, default)

    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([
                "id", "despertar", "fecha", "hora", "lat", "lon",
                "estado", "bateria_v", "bateria_pct", "device", "created_at",
            ])


def ensure_admin():
    users = read_json(USERS_FILE, {})
    current = users.get(ADMIN_USER, {})
    users[ADMIN_USER] = {
        "username": ADMIN_USER,
        "email": ADMIN_USER,
        "name": "Administrador HERMES",
        "password": pwd_context.hash(ADMIN_PASS),
        "role": "admin",
        "created_at": current.get("created_at", datetime.utcnow().isoformat()),
        "updated_at": datetime.utcnow().isoformat(),
    }
    write_json(USERS_FILE, users)


init_files()
ensure_admin()


def create_token(username, role):
    return jwt.encode(
        {"sub": username, "role": role, "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET,
        algorithm="HS256",
    )


def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token requerido")
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        username = payload.get("sub")
        role = payload.get("role", "user")
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
    if request.headers.get("x-device-key") != DEVICE_KEY:
        raise HTTPException(status_code=401, detail="Device key invalida")


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except Exception:
        return None


def in_range(created_at, start, end):
    dt, s, e = parse_dt(created_at), parse_dt(start), parse_dt(end)
    if not dt:
        return True
    if s and dt < s:
        return False
    if e and dt > e:
        return False
    return True


def valid_point(p):
    try:
        return float(p.get("lat", 0)) != 0 and float(p.get("lon", 0)) != 0
    except Exception:
        return False


def public_user(username, role):
    return {"username": username, "email": username, "role": role}


def patched_index_html():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return None

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace(
        'const BASE=location.origin, CICLOS=[5,10,15,30,60], COL=-5, MOV_M=30;',
        'const BACKEND_URL="https://gps-backend-pqzg.onrender.com";\n'
        'const BASE=location.protocol==="file:"||["localhost","127.0.0.1"].includes(location.hostname)||location.hostname.includes("github")?BACKEND_URL:location.origin, CICLOS=[5,10,15,30,60], COL=-5, MOV_M=30;',
    )
    html = html.replace(
        'async function login(){const u=loginEmail.value.trim();const p=loginPass.value;const res=await fetch(BASE+"/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:u,email:u,password:p})});const d=await res.json();if(d.token){TOKEN=d.token;USER=d.user||{email:d.email||u,username:u,role:d.role};ROLE=d.role||USER.role||"user";localStorage.setItem("hermes_token",TOKEN);localStorage.setItem("hermes_role",ROLE);postLogin();log("LOGIN OK: "+(USER.email||USER.username),"ok")}else{loginMsg.style.color="#ff3355";loginMsg.innerText=d.detail||"Credenciales incorrectas"}}',
        'async function login(){const msg=loginMsg;msg.style.color="#00c8ff";msg.innerText="Conectando...";const u=loginEmail.value.trim();const p=loginPass.value;if(!u||!p){msg.style.color="#ff3355";msg.innerText="Usuario y contrasena requeridos";return}try{const res=await fetch(BASE+"/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:u,email:u,password:p})});let d={};try{d=await res.json()}catch(e){throw new Error("Respuesta invalida del servidor")}if(res.ok&&d.token){TOKEN=d.token;USER=d.user||{email:d.email||u,username:u,role:d.role};ROLE=d.role||USER.role||"user";localStorage.setItem("hermes_token",TOKEN);localStorage.setItem("hermes_role",ROLE);msg.innerText="";postLogin();log("LOGIN OK: "+(USER.email||USER.username),"ok")}else{msg.style.color="#ff3355";msg.innerText=d.detail||"Credenciales incorrectas"}}catch(e){msg.style.color="#ff3355";msg.innerText="No se pudo conectar con el backend: "+e.message}}',
    )
    return html


class RegisterModel(BaseModel):
    username: str = ""
    email: str = ""
    name: str = ""
    password: str


class LoginModel(BaseModel):
    username: str = ""
    email: str = ""
    password: str


class UserCreateModel(BaseModel):
    username: str = ""
    email: str = ""
    password: str
    role: str = "user"


class DeviceModel(BaseModel):
    device_id: str = ""
    device: str = ""
    nombre: str = "Sin nombre"
    name: str = ""
    icono: str = "antenna"
    color: str = "#00c8ff"
    owner: str = ""


class AssignModel(BaseModel):
    user_email: str
    device: str


class CommandModel(BaseModel):
    cmd: str
    device: str = "HERMES-01"


@app.get("/")
def home():
    html = patched_index_html()
    if html:
        return HTMLResponse(html)
    return {"ok": True, "msg": "Backend HERMES activo", "error": "static/index.html no encontrado"}


@app.get("/api")
def api_info():
    return {
        "name": "HERMES GPS Backend",
        "status": "online",
        "admin": ADMIN_USER,
        "admin_password": "Configurada",
        "csv": f"{BASE_URL}/files/gps_log.csv",
        "kml": f"{BASE_URL}/files/ruta.kml",
        "health": f"{BASE_URL}/health",
    }


@app.post("/register")
def register(data: RegisterModel):
    users = read_json(USERS_FILE, {})
    username = (data.username or data.email).strip()
    if not username:
        raise HTTPException(status_code=400, detail="Usuario requerido")
    if username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    users[username] = {
        "username": username,
        "email": username,
        "name": data.name or username,
        "password": pwd_context.hash(data.password),
        "role": "user",
        "created_at": datetime.utcnow().isoformat(),
    }
    write_json(USERS_FILE, users)
    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(username, {})
    write_json(DEVICES_FILE, devices)
    return {"ok": True, "msg": "Usuario creado"}


@app.post("/login")
def login(data: LoginModel):
    username = (data.username or data.email).strip()
    password = data.password

    if username.lower() == ADMIN_USER.lower() and password == ADMIN_PASS:
        user = public_user(ADMIN_USER, "admin")
        return {"ok": True, **user, "token": create_token(ADMIN_USER, "admin"), "user": user}

    users = read_json(USERS_FILE, {})
    user = users.get(username)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")
    try:
        password_ok = pwd_context.verify(password, user["password"])
    except Exception:
        password_ok = False
    if not password_ok:
        raise HTTPException(status_code=401, detail="Contrasena incorrecta")

    role = user.get("role", "user")
    public = public_user(username, role)
    return {"ok": True, **public, "token": create_token(username, role), "user": public}


@app.get("/me")
def me(user=Depends(get_user)):
    return user


@app.get("/admin/users")
def admin_users(admin=Depends(require_admin)):
    users = read_json(USERS_FILE, {})
    return [
        {
            "username": username,
            "email": data.get("email", username),
            "role": data.get("role", "user"),
            "created_at": data.get("created_at", ""),
        }
        for username, data in users.items()
    ]


@app.post("/admin/users")
def admin_create_user(data: UserCreateModel, admin=Depends(require_admin)):
    users = read_json(USERS_FILE, {})
    username = (data.username or data.email).strip()
    if not username:
        raise HTTPException(status_code=400, detail="Usuario requerido")
    if username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")
    role = data.role if data.role in ["admin", "user"] else "user"
    users[username] = {
        "username": username,
        "email": username,
        "password": pwd_context.hash(data.password),
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
    }
    write_json(USERS_FILE, users)
    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(username, {})
    write_json(DEVICES_FILE, devices)
    return {"ok": True, "msg": "Usuario creado"}


@app.delete("/admin/users/{username}")
def admin_delete_user(username: str, admin=Depends(require_admin)):
    if username.lower() == ADMIN_USER.lower():
        raise HTTPException(status_code=400, detail="No se puede eliminar el administrador principal")
    users = read_json(USERS_FILE, {})
    devices = read_json(DEVICES_FILE, {})
    users.pop(username, None)
    devices.pop(username, None)
    write_json(USERS_FILE, users)
    write_json(DEVICES_FILE, devices)
    return {"ok": True}


@app.post("/devices")
def add_device(data: DeviceModel, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    device_id = (data.device_id or data.device).strip()
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id requerido")
    nombre = data.nombre if data.nombre != "Sin nombre" else (data.name or device_id)
    owner = data.owner if user["role"] == "admin" and data.owner else user["username"]
    devices.setdefault(owner, {})
    devices[owner][device_id] = {
        "device_id": device_id,
        "device": device_id,
        "nombre": nombre,
        "name": nombre,
        "icono": data.icono or "antenna",
        "color": data.color or "#00c8ff",
        "owner": owner,
        "created_at": datetime.utcnow().isoformat(),
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
    users = read_json(USERS_FILE, {})
    if data.user_email not in users:
        raise HTTPException(status_code=404, detail="Usuario no existe")
    found, old_owner = None, None
    for owner, devs in devices.items():
        if data.device in devs:
            found, old_owner = devs[data.device], owner
            break
    if not found:
        found = {"device_id": data.device, "device": data.device, "nombre": data.device, "name": data.device, "icono": "antenna", "color": "#00c8ff"}
    found["owner"] = data.user_email
    devices.setdefault(data.user_email, {})[data.device] = found
    if old_owner and old_owner != data.user_email:
        devices[old_owner].pop(data.device, None)
    write_json(DEVICES_FILE, devices)
    return {"ok": True, "msg": "Equipo asignado"}


@app.get("/devices")
def list_devices(user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    if user["role"] == "admin":
        result = []
        for owner, devs in devices.items():
            for d in devs.values():
                item = dict(d)
                item["owner"] = owner
                result.append(item)
        return result
    return list(devices.get(user["username"], {}).values())


@app.put("/devices/{device_id}")
def update_device(device_id: str, data: DeviceModel, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    nombre = data.nombre if data.nombre != "Sin nombre" else (data.name or device_id)
    owners = list(devices.keys()) if user["role"] == "admin" else [user["username"]]
    for owner in owners:
        if device_id not in devices.get(owner, {}):
            continue
        new_owner = data.owner if user["role"] == "admin" and data.owner else owner
        dev = devices[owner][device_id]
        dev.update({"nombre": nombre, "name": nombre, "icono": data.icono, "color": data.color, "owner": new_owner, "updated_at": datetime.utcnow().isoformat()})
        if new_owner != owner:
            devices.setdefault(new_owner, {})[device_id] = dev
            devices[owner].pop(device_id, None)
        write_json(DEVICES_FILE, devices)
        return {"ok": True, "device": dev}
    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")


@app.delete("/devices/{device_id}")
def delete_device(device_id: str, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    owners = list(devices.keys()) if user["role"] == "admin" else [user["username"]]
    for owner in owners:
        if device_id in devices.get(owner, {}):
            devices[owner].pop(device_id, None)
            write_json(DEVICES_FILE, devices)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")


@app.post("/device-status")
async def device_status_post(request: Request):
    check_device_key(request)
    data = await request.json()
    now = datetime.utcnow().isoformat()
    status = {
        "device": data.get("device", "HERMES-01"),
        "estado": data.get("estado", "SIN ESTADO"),
        "despertar": data.get("despertar", data.get("wake", 0)),
        "ciclo_min": data.get("ciclo_min", data.get("ciclo", 0)),
        "fallos_gps": data.get("fallos_gps", data.get("fallos", 0)),
        "lat": float(data.get("lat", 0) or 0),
        "lon": float(data.get("lon", 0) or 0),
        "fecha": data.get("fecha", ""),
        "hora": data.get("hora", ""),
        "bateria_v": data.get("bateria_v", data.get("bat_v", 0)),
        "bateria_pct": data.get("bateria_pct", data.get("bat_pct", 0)),
        "wifi": data.get("wifi", "conectado"),
        "created_at": now,
    }
    all_status = read_json(STATUS_FILE, {})
    all_status[status["device"]] = status
    write_json(STATUS_FILE, all_status)
    hist = read_json(HISTORY_FILE, [])
    hist.append(status)
    write_json(HISTORY_FILE, hist)
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow([len(hist), status["despertar"], status["fecha"], status["hora"], status["lat"], status["lon"], status["estado"], status["bateria_v"], status["bateria_pct"], status["device"], now])
    return {"ok": True, "status": status}


@app.get("/device-status")
def device_status_get(device: str = "HERMES-01"):
    return read_json(STATUS_FILE, {}).get(device, {})


@app.get("/status")
def get_all_status():
    return read_json(STATUS_FILE, {})


@app.get("/status/{device_id}")
def get_status(device_id: str):
    status = read_json(STATUS_FILE, {})
    if device_id not in status:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
    return status[device_id]


@app.get("/latest/{device_id}")
def latest(device_id: str):
    records = [h for h in read_json(HISTORY_FILE, []) if h.get("device") == device_id and valid_point(h)]
    if not records:
        raise HTTPException(status_code=404, detail="Sin ubicacion")
    return records[-1]


@app.get("/fleet/latest")
def fleet_latest(devices: str = None):
    status = read_json(STATUS_FILE, {})
    if not devices:
        return status
    selected = [d.strip() for d in devices.split(",") if d.strip()]
    return {d: status.get(d) for d in selected if d in status}


@app.get("/history")
def history(device: str = None, start: str = None, end: str = None):
    result = []
    for h in read_json(HISTORY_FILE, []):
        if device and h.get("device") != device:
            continue
        if not in_range(h.get("created_at", ""), start, end):
            continue
        if valid_point(h):
            result.append(h)
    return result


@app.get("/history/multiple")
def history_multiple(devices: str, start: str = None, end: str = None):
    selected = [d.strip() for d in devices.split(",") if d.strip()]
    result = {dev: [] for dev in selected}
    for h in read_json(HISTORY_FILE, []):
        dev = h.get("device")
        if dev in result and in_range(h.get("created_at", ""), start, end) and valid_point(h):
            result[dev].append(h)
    return result


@app.post("/command")
def set_command(data: CommandModel):
    write_json(COMMAND_FILE, {"device": data.device, "cmd": data.cmd, "created_at": datetime.utcnow().isoformat()})
    return {"ok": True, "cmd": data.cmd}


@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = False):
    cmd = read_json(COMMAND_FILE, {"cmd": "none"})
    if cmd.get("device") not in [None, device] and cmd.get("cmd") != "none":
        return {"device": device, "cmd": "none"}
    if clear:
        write_json(COMMAND_FILE, {"cmd": "none"})
    return cmd


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
    coords = "\n".join(f"{float(p.get('lon', 0))},{float(p.get('lat', 0))},0" for p in data if valid_point(p))
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document><name>Ruta HERMES</name><Placemark><name>Recorrido GPS</name>
<Style><LineStyle><color>ff0000ff</color><width>4</width></LineStyle></Style>
<LineString><tessellate>1</tessellate><coordinates>
{coords}
</coordinates></LineString></Placemark></Document></kml>
'''
    with open(KML_PATH, "w", encoding="utf-8") as f:
        f.write(kml)
    return FileResponse(KML_PATH, media_type="application/vnd.google-earth.kml+xml", filename="ruta.kml")


@app.get("/export/kml")
def export_kml(device: str = None, start: str = None, end: str = None):
    return generar_kml(device=device, start=start, end=end)


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat(), "admin": ADMIN_USER}




