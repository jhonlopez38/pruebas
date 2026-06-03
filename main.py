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

BASE_URL = os.getenv("BASE_URL", "https://gps-backend-pqzg.onrender.com")
SECRET = os.getenv("SECRET", "HERMES_SECRET_2025")
DEVICE_KEY = os.getenv("DEVICE_KEY", "HERMES_DEVICE_KEY_123")

ADMIN_USER = "Hermesadmin"
ADMIN_PASS = "Colombia2026*"

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
    allow_credentials=True,
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
    if not os.path.exists(USERS_FILE):
        write_json(USERS_FILE, {})

    if not os.path.exists(DEVICES_FILE):
        write_json(DEVICES_FILE, {})

    if not os.path.exists(HISTORY_FILE):
        write_json(HISTORY_FILE, [])

    if not os.path.exists(STATUS_FILE):
        write_json(STATUS_FILE, {})

    if not os.path.exists(COMMAND_FILE):
        write_json(COMMAND_FILE, {"cmd": "none"})

    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "id",
                "despertar",
                "fecha",
                "hora",
                "lat",
                "lon",
                "estado",
                "bateria_v",
                "bateria_pct",
                "device",
                "created_at"
            ])


init_files()

users_init = read_json(USERS_FILE, {})

users_init[ADMIN_USER] = {
    "username": ADMIN_USER,
    "password": pwd_context.hash(ADMIN_PASS),
    "role": "admin",
    "created_at": users_init.get(ADMIN_USER, {}).get("created_at", datetime.utcnow().isoformat()),
    "updated_at": datetime.utcnow().isoformat()
}

write_json(USERS_FILE, users_init)


def create_token(username, role):
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token requerido")

    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        username = payload.get("sub")
        role = payload.get("role", "user")

        if not username:
            raise HTTPException(status_code=401, detail="Token inválido")

        return {
            "username": username,
            "role": role
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


def require_admin(user=Depends(get_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo administrador")
    return user


def check_device_key(request: Request):
    key = request.headers.get("x-device-key")

    if key != DEVICE_KEY:
        raise HTTPException(status_code=401, detail="Device key inválida")


def parse_dt(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except Exception:
        return None


def in_range(created_at, start, end):
    dt = parse_dt(created_at)
    s = parse_dt(start)
    e = parse_dt(end)

    if not dt:
        return True

    if s and dt < s:
        return False

    if e and dt > e:
        return False

    return True


def valid_point(p):
    try:
        lat = float(p.get("lat", 0))
        lon = float(p.get("lon", 0))
        return lat != 0 and lon != 0
    except Exception:
        return False


class RegisterModel(BaseModel):
    username: str
    password: str


class LoginModel(BaseModel):
    username: str
    password: str


class UserCreateModel(BaseModel):
    username: str
    password: str
    role: str = "user"


class DeviceModel(BaseModel):
    device_id: str
    nombre: str = "Sin nombre"
    icono: str = "antenna"
    color: str = "#00cfff"
    owner: str = ""


class CommandModel(BaseModel):
    cmd: str


@app.get("/")
def home():
    index_path = os.path.join(STATIC_DIR, "index.html")

    if os.path.exists(index_path):
        return FileResponse(index_path)

    raise HTTPException(status_code=404, detail="static/index.html no encontrado")


@app.get("/api")
def api_info():
    return {
        "name": "HERMES GPS Backend",
        "status": "online",
        "admin": ADMIN_USER,
        "csv": f"{BASE_URL}/files/gps_log.csv",
        "kml": f"{BASE_URL}/files/ruta.kml",
        "health": f"{BASE_URL}/health"
    }


@app.post("/register")
def register(data: RegisterModel):
    users = read_json(USERS_FILE, {})

    if data.username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")

    users[data.username] = {
        "username": data.username,
        "password": pwd_context.hash(data.password),
        "role": "user",
        "created_at": datetime.utcnow().isoformat()
    }

    write_json(USERS_FILE, users)

    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(data.username, {})
    write_json(DEVICES_FILE, devices)

    return {"ok": True, "msg": "Usuario creado"}


@app.post("/login")
def login(data: LoginModel):
    users = read_json(USERS_FILE, {})
    user = users.get(data.username)

    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")

    if not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    role = user.get("role", "user")

    return {
        "ok": True,
        "username": data.username,
        "role": role,
        "token": create_token(data.username, role)
    }


@app.get("/me")
def me(user=Depends(get_user)):
    return user


@app.get("/admin/users")
def admin_users(admin=Depends(require_admin)):
    users = read_json(USERS_FILE, {})

    result = []

    for username, data in users.items():
        result.append({
            "username": username,
            "role": data.get("role", "user"),
            "created_at": data.get("created_at", "")
        })

    return result


@app.post("/admin/users")
def admin_create_user(data: UserCreateModel, admin=Depends(require_admin)):
    users = read_json(USERS_FILE, {})

    if data.username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")

    role = data.role if data.role in ["admin", "user"] else "user"

    users[data.username] = {
        "username": data.username,
        "password": pwd_context.hash(data.password),
        "role": role,
        "created_at": datetime.utcnow().isoformat()
    }

    write_json(USERS_FILE, users)

    devices = read_json(DEVICES_FILE, {})
    devices.setdefault(data.username, {})
    write_json(DEVICES_FILE, devices)

    return {"ok": True, "msg": "Usuario creado"}


@app.delete("/admin/users/{username}")
def admin_delete_user(username: str, admin=Depends(require_admin)):
    if username == ADMIN_USER:
        raise HTTPException(status_code=400, detail="No se puede eliminar el administrador principal")

    users = read_json(USERS_FILE, {})
    devices = read_json(DEVICES_FILE, {})

    if username in users:
        del users[username]
        write_json(USERS_FILE, users)

    if username in devices:
        del devices[username]
        write_json(DEVICES_FILE, devices)

    return {"ok": True}


@app.post("/devices")
def add_device(data: DeviceModel, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    owner = data.owner if user["role"] == "admin" and data.owner else user["username"]

    devices.setdefault(owner, {})

    devices[owner][data.device_id] = {
        "device_id": data.device_id,
        "nombre": data.nombre,
        "icono": data.icono,
        "color": data.color,
        "owner": owner,
        "created_at": datetime.utcnow().isoformat()
    }

    write_json(DEVICES_FILE, devices)

    return {"ok": True, "device": devices[owner][data.device_id]}


@app.get("/devices")
def list_devices(user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})

    if user["role"] == "admin":
        result = []
        for owner, devs in devices.items():
            for d in devs.values():
                d["owner"] = owner
                result.append(d)
        return result

    return list(devices.get(user["username"], {}).values())


@app.put("/devices/{device_id}")
def update_device(device_id: str, data: DeviceModel, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})

    if user["role"] == "admin":
        for owner in list(devices.keys()):
            if device_id in devices[owner]:
                new_owner = data.owner if data.owner else owner
                dev_data = devices[owner][device_id]

                dev_data.update({
                    "nombre": data.nombre,
                    "icono": data.icono,
                    "color": data.color,
                    "owner": new_owner,
                    "updated_at": datetime.utcnow().isoformat()
                })

                if new_owner != owner:
                    devices.setdefault(new_owner, {})
                    devices[new_owner][device_id] = dev_data
                    del devices[owner][device_id]

                write_json(DEVICES_FILE, devices)
                return {"ok": True, "device": dev_data}

    else:
        owner = user["username"]

        if owner in devices and device_id in devices[owner]:
            devices[owner][device_id].update({
                "nombre": data.nombre,
                "icono": data.icono,
                "color": data.color,
                "updated_at": datetime.utcnow().isoformat()
            })

            write_json(DEVICES_FILE, devices)
            return {"ok": True, "device": devices[owner][device_id]}

    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")


@app.delete("/devices/{device_id}")
def delete_device(device_id: str, user=Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})

    if user["role"] == "admin":
        for owner in list(devices.keys()):
            if device_id in devices[owner]:
                del devices[owner][device_id]
                write_json(DEVICES_FILE, devices)
                return {"ok": True}

    else:
        owner = user["username"]

        if owner in devices and device_id in devices[owner]:
            del devices[owner][device_id]
            write_json(DEVICES_FILE, devices)
            return {"ok": True}

    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")


@app.post("/device-status")
async def device_status(request: Request):
    check_device_key(request)
    data = await request.json()

    device = data.get("device", "HERMES-01")
    estado = data.get("estado", "SIN ESTADO")
    despertar = data.get("despertar", data.get("wake", 0))
    ciclo_min = data.get("ciclo_min", data.get("ciclo", 0))
    fallos_gps = data.get("fallos_gps", data.get("fallos", 0))

    lat = float(data.get("lat", 0) or 0)
    lon = float(data.get("lon", 0) or 0)

    fecha = data.get("fecha", "")
    hora = data.get("hora", "")

    bateria_v = data.get("bateria_v", data.get("bat_v", 0))
    bateria_pct = data.get("bateria_pct", data.get("bat_pct", 0))

    now = datetime.utcnow().isoformat()

    status = {
        "device": device,
        "estado": estado,
        "despertar": despertar,
        "ciclo_min": ciclo_min,
        "fallos_gps": fallos_gps,
        "lat": lat,
        "lon": lon,
        "fecha": fecha,
        "hora": hora,
        "bateria_v": bateria_v,
        "bateria_pct": bateria_pct,
        "created_at": now
    }

    all_status = read_json(STATUS_FILE, {})
    all_status[device] = status
    write_json(STATUS_FILE, all_status)

    history = read_json(HISTORY_FILE, [])
    history.append(status)
    write_json(HISTORY_FILE, history)

    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            len(history),
            despertar,
            fecha,
            hora,
            lat,
            lon,
            estado,
            bateria_v,
            bateria_pct,
            device,
            now
        ])

    return {"ok": True, "status": status}


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
    history = read_json(HISTORY_FILE, [])

    registros = [
        h for h in history
        if h.get("device") == device_id and valid_point(h)
    ]

    if not registros:
        raise HTTPException(status_code=404, detail="Sin ubicación")

    return registros[-1]


@app.get("/fleet/latest")
def fleet_latest(devices: str = None):
    status = read_json(STATUS_FILE, {})

    if not devices:
        return status

    selected = [d.strip() for d in devices.split(",") if d.strip()]

    return {
        d: status.get(d)
        for d in selected
        if d in status
    }


@app.get("/history")
def history(device: str = None, start: str = None, end: str = None):
    data = read_json(HISTORY_FILE, [])
    result = []

    for h in data:
        if device and h.get("device") != device:
            continue

        if not in_range(h.get("created_at", ""), start, end):
            continue

        if not valid_point(h):
            continue

        result.append(h)

    return result


@app.get("/history/multiple")
def history_multiple(devices: str, start: str = None, end: str = None):
    selected = [d.strip() for d in devices.split(",") if d.strip()]
    data = read_json(HISTORY_FILE, [])

    result = {dev: [] for dev in selected}

    for h in data:
        dev = h.get("device")

        if dev not in selected:
            continue

        if not in_range(h.get("created_at", ""), start, end):
            continue

        if not valid_point(h):
            continue

        result[dev].append(h)

    return result


@app.post("/command")
def set_command(data: CommandModel):
    write_json(COMMAND_FILE, {
        "cmd": data.cmd,
        "created_at": datetime.utcnow().isoformat()
    })

    return {"ok": True, "cmd": data.cmd}


@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = False):
    cmd = read_json(COMMAND_FILE, {"cmd": "none"})

    if clear:
        write_json(COMMAND_FILE, {"cmd": "none"})

    return cmd


@app.get("/files/gps_log.csv")
def download_csv():
    if not os.path.exists(CSV_PATH):
        raise HTTPException(status_code=404, detail="gps_log.csv no encontrado")

    return FileResponse(
        CSV_PATH,
        media_type="text/csv",
        filename="gps_log.csv"
    )


@app.get("/files/ruta.kml")
def generar_kml(device: str = None, start: str = None, end: str = None):
    data = history(device=device, start=start, end=end)

    if not data:
        raise HTTPException(status_code=404, detail="No hay puntos GPS válidos")

    coords = ""

    for p in data:
        lat = float(p.get("lat", 0))
        lon = float(p.get("lon", 0))

        if lat != 0 and lon != 0:
            coords += f"{lon},{lat},0\n"

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
<name>Ruta HERMES</name>
<Placemark>
<name>Recorrido GPS</name>
<Style>
<LineStyle>
<color>ff0000ff</color>
<width>4</width>
</LineStyle>
</Style>
<LineString>
<tessellate>1</tessellate>
<coordinates>
{coords}
</coordinates>
</LineString>
</Placemark>
</Document>
</kml>
"""

    with open(KML_PATH, "w", encoding="utf-8") as f:
        f.write(kml)

    return FileResponse(
        KML_PATH,
        media_type="application/vnd.google-earth.kml+xml",
        filename="ruta.kml"
    )


@app.get("/export/kml")
def export_kml(device: str = None, start: str = None, end: str = None):
    return generar_kml(device=device, start=start, end=end)


@app.get("/health")
def health():
    return {
        "ok": True,
        "time": datetime.utcnow().isoformat()
    }
