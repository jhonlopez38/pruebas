import os
import json
import csv
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
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

app = FastAPI(title="HERMES GPS")

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
                "id", "despertar", "fecha", "hora", "lat", "lon",
                "estado", "bateria_v", "bateria_pct", "device", "created_at"
            ])


init_files()

users_init = read_json(USERS_FILE, {})
if ADMIN_USER not in users_init:
    users_init[ADMIN_USER] = {
        "username": ADMIN_USER,
        "password": pwd_context.hash(ADMIN_PASS),
        "role": "admin",
        "created_at": datetime.utcnow().isoformat()
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

        return {"username": username, "role": role}

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
    icono: str = "car"
    color: str = "#007bff"
    owner: str = ""


class CommandModel(BaseModel):
    cmd: str


@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(APP_HTML)


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

    return {"ok": True}


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
        for owner in devices:
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
            len(history), despertar, fecha, hora, lat, lon,
            estado, bateria_v, bateria_pct, device, now
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
    return {d: status.get(d) for d in selected if d in status}


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

    return FileResponse(CSV_PATH, media_type="text/csv", filename="gps_log.csv")


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

    return FileResponse(KML_PATH, media_type="application/vnd.google-earth.kml+xml", filename="ruta.kml")


@app.get("/export/kml")
def export_kml(device: str = None, start: str = None, end: str = None):
    return generar_kml(device=device, start=start, end=end)


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}


APP_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>HERMES GPS</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css">

<style>
body{margin:0;font-family:Arial;background:#0b0f19;color:white}
header{padding:12px;background:#111827;display:flex;justify-content:space-between;align-items:center}
button,input,select{padding:9px;border-radius:8px;border:1px solid #374151;margin:4px}
button{background:#2563eb;color:white;cursor:pointer}
button:hover{background:#1d4ed8}
.panel{display:flex;height:calc(100vh - 55px)}
.sidebar{width:380px;background:#111827;padding:12px;overflow:auto}
.map{flex:1}
#map{height:100%;width:100%}
.card{background:#1f2937;margin:8px 0;padding:10px;border-radius:10px}
.hidden{display:none}
.deviceItem{padding:8px;background:#374151;border-radius:8px;margin:4px 0}
.tabs button{background:#374151}
.tabs button.active{background:#10b981}
.small{font-size:12px;color:#9ca3af}
.progress{width:100%}
</style>
</head>

<body>

<header>
  <b>🛰 HERMES GPS</b>
  <div>
    <span id="userLabel"></span>
    <button onclick="logout()">Salir</button>
  </div>
</header>

<div id="authView" class="sidebar" style="width:auto;height:100vh">
  <h2>Ingreso HERMES</h2>
  <input id="loginUser" placeholder="Usuario">
  <input id="loginPass" placeholder="Contraseña" type="password">
  <button onclick="login()">Ingresar</button>
  <p>Admin fijo: Hermesadmin / Colombia2026*</p>
  <p id="authMsg"></p>
</div>

<div id="appView" class="panel hidden">
  <div class="sidebar">

    <div class="tabs">
      <button class="active" onclick="showTab('live')">Mapa</button>
      <button onclick="showTab('history')">Historial</button>
      <button onclick="showTab('devices')">Equipos</button>
      <button id="adminTabBtn" class="hidden" onclick="showTab('admin')">Usuarios</button>
    </div>

    <div id="tab_live">
      <h3>Mapa en vivo</h3>
      <div id="deviceCheckboxes"></div>
      <button onclick="loadSelectedLatest()">Mostrar seleccionados</button>
      <button onclick="centerAll()">Centrar todos</button>
      <div id="liveInfo"></div>
    </div>

    <div id="tab_history" class="hidden">
      <h3>Recorrido tipo Strava</h3>
      <select id="historyDevice"></select>
      <input id="startDate" type="datetime-local">
      <input id="endDate" type="datetime-local">
      <button onclick="loadHistory()">Consultar</button>
      <button onclick="playRoute()">▶ Play</button>
      <button onclick="pauseRoute()">⏸ Pausa</button>
      <button onclick="resetRoute()">⏮ Reiniciar</button>
      <select id="playSpeed">
        <option value="1000">1x</option>
        <option value="500">2x</option>
        <option value="250">4x</option>
        <option value="100">10x</option>
      </select>
      <input id="routeProgress" class="progress" type="range" min="0" max="0" value="0" oninput="jumpRoute(this.value)">
      <button onclick="downloadKML()">Descargar KML</button>
      <div id="historyStats" class="card"></div>
    </div>

    <div id="tab_devices" class="hidden">
      <h3>Administrar equipos</h3>
      <input id="devId" placeholder="DEVICE_ID">
      <input id="devName" placeholder="Nombre">
      <select id="devIcon">
        <option value="car">🚗 Carro</option>
        <option value="motorcycle">🏍️ Moto</option>
        <option value="truck">🚚 Camión</option>
        <option value="bus">🚌 Bus</option>
        <option value="person">🚶 Persona</option>
        <option value="box">📦 Activo</option>
        <option value="boat">🛥️ Lancha</option>
      </select>
      <input id="devColor" type="color" value="#007bff">
      <select id="devOwner"></select>
      <button onclick="saveDevice()">Guardar / Editar</button>
      <div id="deviceList"></div>
    </div>

    <div id="tab_admin" class="hidden">
      <h3>Usuarios</h3>
      <input id="newUser" placeholder="Nuevo usuario">
      <input id="newPass" placeholder="Contraseña" type="password">
      <select id="newRole">
        <option value="user">Usuario</option>
        <option value="admin">Administrador</option>
      </select>
      <button onclick="createUser()">Crear usuario</button>
      <div id="usersList"></div>
    </div>

  </div>

  <div class="map">
    <div id="map"></div>
  </div>
</div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>
let token = localStorage.getItem("token") || "";
let username = localStorage.getItem("username") || "";
let role = localStorage.getItem("role") || "";
let devices = [];
let users = [];
let map;
let markers = {};
let routeLine = null;
let routeMarker = null;
let routePoints = [];
let playIndex = 0;
let playTimer = null;

const iconEmoji = {
  car:"🚗",
  motorcycle:"🏍️",
  truck:"🚚",
  bus:"🚌",
  person:"🚶",
  box:"📦",
  boat:"🛥️"
};

function authHeaders(){
  return {"Authorization":"Bearer " + token, "Content-Type":"application/json"};
}

async function login(){
  const r = await fetch("/login", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({username:loginUser.value,password:loginPass.value})
  });

  const j = await r.json();

  if(j.ok){
    token = j.token;
    username = j.username;
    role = j.role;
    localStorage.setItem("token", token);
    localStorage.setItem("username", username);
    localStorage.setItem("role", role);
    startApp();
  }else{
    authMsg.innerText = j.detail || "Error";
  }
}

function logout(){
  localStorage.clear();
  location.reload();
}

function initMap(){
  map = L.map("map").setView([4.65,-74.1], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{
    attribution:"OpenStreetMap"
  }).addTo(map);
}

function showTab(name){
  ["live","history","devices","admin"].forEach(t=>{
    document.getElementById("tab_"+t).classList.add("hidden");
  });
  document.getElementById("tab_"+name).classList.remove("hidden");
}

async function loadUsers(){
  if(role !== "admin") return;
  const r = await fetch("/admin/users",{headers:authHeaders()});
  users = await r.json();

  usersList.innerHTML = "";
  devOwner.innerHTML = "";

  users.forEach(u=>{
    usersList.innerHTML += `
      <div class="card">
        <b>${u.username}</b><br>
        Rol: ${u.role}<br>
        <button onclick="deleteUser('${u.username}')">Eliminar</button>
      </div>
    `;

    devOwner.innerHTML += `<option value="${u.username}">${u.username}</option>`;
  });
}

async function createUser(){
  await fetch("/admin/users",{
    method:"POST",
    headers:authHeaders(),
    body:JSON.stringify({
      username:newUser.value,
      password:newPass.value,
      role:newRole.value
    })
  });

  newUser.value="";
  newPass.value="";
  await loadUsers();
}

async function deleteUser(u){
  await fetch("/admin/users/"+u,{
    method:"DELETE",
    headers:authHeaders()
  });
  await loadUsers();
}

async function loadDevices(){
  const r = await fetch("/devices", {headers:authHeaders()});
  devices = await r.json();

  renderDeviceSelectors();
  renderDeviceList();
}

function renderDeviceSelectors(){
  deviceCheckboxes.innerHTML = "";
  historyDevice.innerHTML = "";

  devices.forEach(d=>{
    const emoji = iconEmoji[d.icono] || "📍";

    deviceCheckboxes.innerHTML += `
      <div class="deviceItem">
        <label>
          <input type="checkbox" class="devCheck" value="${d.device_id}" checked>
          ${emoji} ${d.nombre} <span class="small">${d.device_id}</span>
        </label>
      </div>
    `;

    historyDevice.innerHTML += `<option value="${d.device_id}">${emoji} ${d.nombre}</option>`;
  });
}

function renderDeviceList(){
  deviceList.innerHTML = "";

  devices.forEach(d=>{
    const emoji = iconEmoji[d.icono] || "📍";

    deviceList.innerHTML += `
      <div class="card">
        <b>${emoji} ${d.nombre}</b><br>
        <span class="small">${d.device_id}</span><br>
        Owner: ${d.owner || username}<br>
        <button onclick="editDevice('${d.device_id}')">Editar</button>
        <button onclick="deleteDevice('${d.device_id}')">Eliminar</button>
      </div>
    `;
  });
}

function editDevice(id){
  const d = devices.find(x=>x.device_id===id);
  if(!d) return;

  devId.value = d.device_id;
  devName.value = d.nombre;
  devIcon.value = d.icono;
  devColor.value = d.color;
  if(d.owner) devOwner.value = d.owner;
}

async function saveDevice(){
  const payload = {
    device_id:devId.value,
    nombre:devName.value,
    icono:devIcon.value,
    color:devColor.value,
    owner:devOwner.value || username
  };

  const exists = devices.find(d=>d.device_id===payload.device_id);
  const url = exists ? "/devices/" + payload.device_id : "/devices";
  const method = exists ? "PUT" : "POST";

  await fetch(url,{method,headers:authHeaders(),body:JSON.stringify(payload)});
  await loadDevices();
}

async function deleteDevice(id){
  await fetch("/devices/" + id,{method:"DELETE",headers:authHeaders()});
  await loadDevices();
}

function makeIcon(d){
  const emoji = iconEmoji[d.icono] || "📍";
  return L.divIcon({
    html:`<div style="font-size:28px">${emoji}</div>`,
    className:"",
    iconSize:[30,30]
  });
}

async function loadSelectedLatest(){
  const selected = [...document.querySelectorAll(".devCheck:checked")].map(x=>x.value);
  if(selected.length === 0) return;

  const r = await fetch("/fleet/latest?devices=" + selected.join(","));
  const data = await r.json();

  liveInfo.innerHTML = "";

  for(const id of selected){
    const p = data[id];
    const d = devices.find(x=>x.device_id===id) || {icono:"car", nombre:id};

    if(!p || !p.lat || !p.lon) continue;

    const latlng = [p.lat, p.lon];

    if(markers[id]){
      markers[id].setLatLng(latlng);
    }else{
      markers[id] = L.marker(latlng, {icon:makeIcon(d)}).addTo(map);
    }

    markers[id].bindPopup(`
      <b>${d.nombre}</b><br>
      ${id}<br>
      ${p.estado}<br>
      Batería: ${p.bateria_pct}%<br>
      ${p.fecha} ${p.hora}
    `);

    liveInfo.innerHTML += `
      <div class="card">
        <b>${iconEmoji[d.icono] || "📍"} ${d.nombre}</b><br>
        Estado: ${p.estado}<br>
        Batería: ${p.bateria_pct}%<br>
        Última: ${p.fecha} ${p.hora}
      </div>
    `;
  }

  centerAll();
}

function centerAll(){
  const arr = Object.values(markers);
  if(arr.length === 0) return;
  const group = L.featureGroup(arr);
  map.fitBounds(group.getBounds().pad(0.2));
}

async function loadHistory(){
  clearRoute();

  const dev = historyDevice.value;
  const start = startDate.value ? new Date(startDate.value).toISOString() : "";
  const end = endDate.value ? new Date(endDate.value).toISOString() : "";

  const r = await fetch(`/history?device=${dev}&start=${start}&end=${end}`);
  routePoints = await r.json();

  if(routePoints.length === 0){
    historyStats.innerHTML = "Sin puntos en ese rango.";
    return;
  }

  const latlngs = routePoints.map(p=>[p.lat,p.lon]);

  routeLine = L.polyline(latlngs, {weight:5}).addTo(map);
  L.marker(latlngs[0]).addTo(map).bindPopup("Inicio");
  L.marker(latlngs[latlngs.length-1]).addTo(map).bindPopup("Fin");

  routeMarker = L.marker(latlngs[0]).addTo(map);
  map.fitBounds(routeLine.getBounds().pad(0.2));

  routeProgress.max = routePoints.length - 1;
  routeProgress.value = 0;

  historyStats.innerHTML = `
    <b>Puntos:</b> ${routePoints.length}<br>
    <b>Inicio:</b> ${routePoints[0].fecha} ${routePoints[0].hora}<br>
    <b>Fin:</b> ${routePoints[routePoints.length-1].fecha} ${routePoints[routePoints.length-1].hora}
  `;
}

function playRoute(){
  if(routePoints.length === 0) return;
  pauseRoute();

  const speed = parseInt(playSpeed.value);

  playTimer = setInterval(()=>{
    if(playIndex >= routePoints.length){
      pauseRoute();
      return;
    }

    const p = routePoints[playIndex];
    routeMarker.setLatLng([p.lat,p.lon]);
    routeProgress.value = playIndex;
    playIndex++;
  }, speed);
}

function pauseRoute(){
  if(playTimer){
    clearInterval(playTimer);
    playTimer = null;
  }
}

function resetRoute(){
  pauseRoute();
  playIndex = 0;
  routeProgress.value = 0;
  if(routePoints.length && routeMarker){
    const p = routePoints[0];
    routeMarker.setLatLng([p.lat,p.lon]);
  }
}

function jumpRoute(i){
  playIndex = parseInt(i);
  if(routePoints.length && routeMarker){
    const p = routePoints[playIndex];
    routeMarker.setLatLng([p.lat,p.lon]);
  }
}

function clearRoute(){
  pauseRoute();
  playIndex = 0;
  if(routeLine){map.removeLayer(routeLine);routeLine=null}
  if(routeMarker){map.removeLayer(routeMarker);routeMarker=null}
}

function downloadKML(){
  const dev = historyDevice.value;
  const start = startDate.value ? new Date(startDate.value).toISOString() : "";
  const end = endDate.value ? new Date(endDate.value).toISOString() : "";
  window.open(`/files/ruta.kml?device=${dev}&start=${start}&end=${end}`, "_blank");
}

async function startApp(){
  authView.classList.add("hidden");
  appView.classList.remove("hidden");
  userLabel.innerText = username + " (" + role + ")";

  if(role === "admin"){
    adminTabBtn.classList.remove("hidden");
  }

  initMap();
  await loadUsers();
  await loadDevices();

  setInterval(loadSelectedLatest, 30000);
}

if(token){
  startApp();
}
</script>

</body>
</html>
"""
