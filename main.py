import os
import json
import shutil
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pydantic import BaseModel
from jose import jwt
from passlib.context import CryptContext

BASE_URL = "https://gps-backend-pqzg.onrender.com"
SECRET = os.getenv("SECRET", "HERMES_SECRET_2025")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "HERMES_DEVICE_KEY_123")

STATIC_DIR = "static"
FILES_DIR = "static/files"
DATA_DIR = "data"

COMMAND_FILE = os.path.join(FILES_DIR, "command.json")
STATUS_FILE = os.path.join(FILES_DIR, "status.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
ASSIGN_FILE = os.path.join(DATA_DIR, "assignments.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="Hermes GPS Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/files", StaticFiles(directory=FILES_DIR), name="files")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


class RegisterModel(BaseModel):
    name: str
    email: str
    password: str


class LoginModel(BaseModel):
    email: str
    password: str


class AssignModel(BaseModel):
    user_email: str
    device: str


class DeviceModel(BaseModel):
    device: str
    name: str = ""


class CommandModel(BaseModel):
    device: str = "HERMES-01"
    cmd: str = "none"


def now():
    return datetime.utcnow().isoformat() + "Z"


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
        json.dump(data, f, ensure_ascii=False, indent=2)


def hash_password(password):
    return pwd_context.hash(password)


def verify_password(password, hashed):
    return pwd_context.verify(password, hashed)


def create_token(user):
    payload = {
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="No autorizado")

    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    users = read_json(USERS_FILE, [])
    for user in users:
        if user["email"] == payload["email"]:
            return user

    raise HTTPException(status_code=401, detail="Usuario no existe")


def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Solo administrador")
    return user


def init_admin():
    users = read_json(USERS_FILE, [])

    exists = any(u["email"] == "admin@gps.com" for u in users)

    if not exists:
        users.append({
            "name": "Administrador",
            "email": "admin@gps.com",
            "password": hash_password("admin123"),
            "role": "admin",
            "active": True,
            "created_at": now()
        })
        write_json(USERS_FILE, users)


init_admin()


@app.get("/")
def home():
    index_path = os.path.join(STATIC_DIR, "index.html")

    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")

    return {
        "status": "HERMES GPS ONLINE",
        "message": "Sube static/index.html para ver la web app"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "Hermes GPS Backend",
        "web": BASE_URL,
        "index_exists": os.path.isfile(os.path.join(STATIC_DIR, "index.html")),
        "timestamp_utc": now()
    }


@app.get("/links")
def links():
    return {
        "status": "ok",
        "service": "Hermes GPS Backend",
        "web": BASE_URL,
        "health": f"{BASE_URL}/health",
        "device_status": f"{BASE_URL}/device-status",
        "command": f"{BASE_URL}/command",
        "csv": f"{BASE_URL}/files/gps_log.csv",
        "kml": f"{BASE_URL}/files/ruta.kml",
    }


@app.post("/register")
def register(data: RegisterModel):
    users = read_json(USERS_FILE, [])

    for user in users:
        if user["email"].lower() == data.email.lower():
            raise HTTPException(status_code=400, detail="Usuario ya existe")

    user = {
        "name": data.name,
        "email": data.email.lower(),
        "password": hash_password(data.password),
        "role": "user",
        "active": True,
        "created_at": now()
    }

    users.append(user)
    write_json(USERS_FILE, users)

    return {"status": "ok", "message": "Usuario registrado"}


@app.post("/login")
def login(data: LoginModel):
    users = read_json(USERS_FILE, [])

    for user in users:
        if user["email"].lower() == data.email.lower():
            if not user.get("active", True):
                raise HTTPException(status_code=403, detail="Usuario inactivo")

            if verify_password(data.password, user["password"]):
                return {
                    "status": "ok",
                    "token": create_token(user),
                    "user": {
                        "name": user["name"],
                        "email": user["email"],
                        "role": user["role"]
                    }
                }

    raise HTTPException(status_code=401, detail="Credenciales inválidas")


@app.get("/me")
def me(user=Depends(get_current_user)):
    return {
        "name": user["name"],
        "email": user["email"],
        "role": user["role"]
    }


@app.get("/admin/users")
def admin_users(user=Depends(require_admin)):
    users = read_json(USERS_FILE, [])

    clean = []
    for u in users:
        clean.append({
            "name": u["name"],
            "email": u["email"],
            "role": u["role"],
            "active": u.get("active", True),
            "created_at": u.get("created_at", "")
        })

    return clean


@app.post("/admin/device")
def admin_add_device(data: DeviceModel, user=Depends(require_admin)):
    devices = read_json(DEVICES_FILE, [])

    exists = any(d["device"] == data.device for d in devices)

    if not exists:
        devices.append({
            "device": data.device,
            "name": data.name or data.device,
            "created_at": now(),
            "active": True
        })
        write_json(DEVICES_FILE, devices)

    return {"status": "ok", "device": data.device}


@app.get("/admin/devices")
def admin_devices(user=Depends(require_admin)):
    return read_json(DEVICES_FILE, [])


@app.post("/admin/assign")
def admin_assign(data: AssignModel, user=Depends(require_admin)):
    assignments = read_json(ASSIGN_FILE, [])

    exists = any(
        a["user_email"] == data.user_email.lower() and a["device"] == data.device
        for a in assignments
    )

    if not exists:
        assignments.append({
            "user_email": data.user_email.lower(),
            "device": data.device,
            "created_at": now()
        })
        write_json(ASSIGN_FILE, assignments)

    return {"status": "ok", "message": "Equipo asignado"}


@app.get("/devices")
def get_user_devices(user=Depends(get_current_user)):
    devices = read_json(DEVICES_FILE, [])
    assignments = read_json(ASSIGN_FILE, [])
    status = read_json(STATUS_FILE, {})
    history = read_json(HISTORY_FILE, [])

    if user["role"] == "admin":
        allowed = [d["device"] for d in devices]
    else:
        allowed = [
            a["device"] for a in assignments
            if a["user_email"] == user["email"].lower()
        ]

    result = []

    for device in allowed:
        last = None

        if status.get("device") == device:
            last = status
        else:
            for item in reversed(history):
                if item.get("device") == device:
                    last = item
                    break

        result.append({
            "device": device,
            "status": last or {"status": "no_data"}
        })

    return result


@app.post("/upload/{filename}")
async def upload_file(filename: str, request: Request):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(FILES_DIR, safe_name)

    body = await request.body()

    if not body:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Cuerpo vacío"}
        )

    with open(file_path, "wb") as f:
        f.write(body)

    return {
        "status": "ok",
        "filename": safe_name,
        "bytes": len(body),
        "url": f"{BASE_URL}/files/{safe_name}"
    }


@app.post("/upload")
async def upload_file_form(file: UploadFile = File(...)):
    safe_name = os.path.basename(file.filename)
    file_path = os.path.join(FILES_DIR, safe_name)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "status": "ok",
        "filename": safe_name,
        "url": f"{BASE_URL}/files/{safe_name}"
    }


@app.post("/command")
async def set_command(request: Request):
    data = await request.json()

    cmd = str(data.get("cmd", "none")).strip().lower()
    device = str(data.get("device", "HERMES-01")).strip()

    payload = {
        "status": "pending",
        "device": device,
        "cmd": cmd,
        "created_at": now()
    }

    write_json(COMMAND_FILE, payload)

    return {
        "status": "ok",
        "message": "Comando guardado",
        "command": payload
    }


@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = False):
    default = {
        "status": "none",
        "device": device,
        "cmd": "none"
    }

    data = read_json(COMMAND_FILE, default)

    if data.get("device", device) != device:
        return default

    if clear and data.get("cmd", "none") != "none":
        write_json(COMMAND_FILE, {
            "status": "none",
            "device": device,
            "cmd": "none",
            "cleared_at": now()
        })

    return data


@app.post("/device-status")
async def set_device_status(request: Request):
    data = await request.json()

    data["updated_at"] = now()

    if "device" not in data:
        data["device"] = "HERMES-01"

    write_json(STATUS_FILE, data)

    history = read_json(HISTORY_FILE, [])
    history.append(data)

    if len(history) > 1000:
        history = history[-1000:]

    write_json(HISTORY_FILE, history)

    devices = read_json(DEVICES_FILE, [])
    exists = any(d["device"] == data["device"] for d in devices)

    if not exists:
        devices.append({
            "device": data["device"],
            "name": data["device"],
            "created_at": now(),
            "active": True
        })
        write_json(DEVICES_FILE, devices)

    return {
        "status": "ok",
        "device_status": data
    }


@app.get("/device-status")
def get_device_status():
    return read_json(STATUS_FILE, {
        "status": "no_data",
        "message": "El ESP32 aún no ha enviado estado"
    })


@app.get("/history")
def get_history(device: str = "HERMES-01"):
    history = read_json(HISTORY_FILE, [])

    filtered = [
        item for item in history
        if item.get("device") == device
    ]

    return filtered[-200:]


@app.get("/gps-log")
def get_gps_log():
    path = os.path.join(FILES_DIR, "gps_log.csv")

    if os.path.isfile(path):
        return FileResponse(path, media_type="text/csv", filename="gps_log.csv")

    return JSONResponse(
        status_code=404,
        content={"status": "error", "message": "gps_log.csv no existe"}
    )


@app.get("/ruta-kml")
def get_ruta_kml():
    path = os.path.join(FILES_DIR, "ruta.kml")

    if os.path.isfile(path):
        return FileResponse(path, media_type="application/vnd.google-earth.kml+xml", filename="ruta.kml")

    return JSONResponse(
        status_code=404,
        content={"status": "error", "message": "ruta.kml no existe"}
    )
