import os
import json
import csv
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext

BASE_URL = "https://gps-backend-pqzg.onrender.com"
SECRET = os.getenv("SECRET", "HERMES_SECRET_2025")
DEVICE_KEY = os.getenv("DEVICE_KEY", "HERMES_DEVICE_KEY_123")

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
security = HTTPBearer()


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


def create_token(username):
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token inválido")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")


def validar_device_key(request: Request):
    key = request.headers.get("x-device-key")
    if key != DEVICE_KEY:
        raise HTTPException(status_code=401, detail="Device key inválida")


def init_files():
    if not os.path.exists(USERS_FILE):
        write_json(USERS_FILE, {})

    if not os.path.exists(DEVICES_FILE):
        write_json(DEVICES_FILE, {})

    if not os.path.exists(HISTORY_FILE):
        write_json(HISTORY_FILE, [])

    if not os.path.exists(COMMAND_FILE):
        write_json(COMMAND_FILE, {"cmd": "none"})

    if not os.path.exists(STATUS_FILE):
        write_json(STATUS_FILE, {})

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


class RegisterModel(BaseModel):
    username: str
    password: str


class LoginModel(BaseModel):
    username: str
    password: str


class DeviceModel(BaseModel):
    device_id: str
    nombre: str = "Sin nombre"
    icono: str = "car"
    color: str = "#007bff"


class CommandModel(BaseModel):
    cmd: str


@app.get("/")
def root():
    return {
        "name": "HERMES GPS Backend",
        "status": "online",
        "files": f"{BASE_URL}/files/gps_log.csv",
        "kml": f"{BASE_URL}/files/ruta.kml"
    }


@app.post("/register")
def register(data: RegisterModel):
    users = read_json(USERS_FILE, {})

    if data.username in users:
        raise HTTPException(status_code=400, detail="Usuario ya existe")

    users[data.username] = {
        "username": data.username,
        "password": pwd_context.hash(data.password),
        "created_at": datetime.utcnow().isoformat()
    }

    write_json(USERS_FILE, users)

    return {"ok": True, "msg": "Usuario creado"}


@app.post("/login")
def login(data: LoginModel):
    users = read_json(USERS_FILE, {})
    user = users.get(data.username)

    if not user:
        raise HTTPException(status_code=401, detail="Usuario no existe")

    if not pwd_context.verify(data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")

    token = create_token(data.username)

    return {
        "ok": True,
        "token": token,
        "username": data.username
    }


@app.get("/me")
def me(username: str = Depends(get_user)):
    return {"username": username}


@app.post("/devices")
def add_device(data: DeviceModel, username: str = Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})

    if username not in devices:
        devices[username] = {}

    devices[username][data.device_id] = {
        "device_id": data.device_id,
        "nombre": data.nombre,
        "icono": data.icono,
        "color": data.color,
        "created_at": datetime.utcnow().isoformat()
    }

    write_json(DEVICES_FILE, devices)

    return {"ok": True, "device": devices[username][data.device_id]}


@app.get("/devices")
def list_devices(username: str = Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})
    return list(devices.get(username, {}).values())


@app.put("/devices/{device_id}")
def update_device(device_id: str, data: DeviceModel, username: str = Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})

    if username not in devices or device_id not in devices[username]:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")

    devices[username][device_id].update({
        "nombre": data.nombre,
        "icono": data.icono,
        "color": data.color,
        "updated_at": datetime.utcnow().isoformat()
    })

    write_json(DEVICES_FILE, devices)

    return {"ok": True, "device": devices[username][device_id]}


@app.delete("/devices/{device_id}")
def delete_device(device_id: str, username: str = Depends(get_user)):
    devices = read_json(DEVICES_FILE, {})

    if username in devices and device_id in devices[username]:
        del devices[username][device_id]
        write_json(DEVICES_FILE, devices)
        return {"ok": True}

    raise HTTPException(status_code=404, detail="Dispositivo no encontrado")


@app.post("/device-status")
async def device_status(request: Request):
    validar_device_key(request)

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
        if h.get("device") == device_id and float(h.get("lat", 0)) != 0 and float(h.get("lon", 0)) != 0
    ]

    if not registros:
        raise HTTPException(status_code=404, detail="Sin ubicación")

    return registros[-1]


@app.get("/history")
def history(
    device: str = None,
    start: str = None,
    end: str = None
):
    data = read_json(HISTORY_FILE, [])

    result = []

    for h in data:
        if device and h.get("device") != device:
            continue

        created_at = h.get("created_at", "")

        if start and created_at < start:
            continue

        if end and created_at > end:
            continue

        if float(h.get("lat", 0)) == 0 and float(h.get("lon", 0)) == 0:
            continue

        result.append(h)

    return result


@app.get("/history/multiple")
def history_multiple(
    devices: str,
    start: str = None,
    end: str = None
):
    selected = [d.strip() for d in devices.split(",") if d.strip()]
    data = read_json(HISTORY_FILE, [])

    result = {}

    for dev in selected:
        result[dev] = []

    for h in data:
        dev = h.get("device")

        if dev not in selected:
            continue

        created_at = h.get("created_at", "")

        if start and created_at < start:
            continue

        if end and created_at > end:
            continue

        if float(h.get("lat", 0)) == 0 and float(h.get("lon", 0)) == 0:
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
