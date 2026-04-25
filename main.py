# ================================================================
#  HERMES GPS — BACKEND (main.py)
#  Plataforma: Render.com
#  Start command: uvicorn main:app --host 0.0.0.0 --port 10000
#  Build command: pip install -r requirements.txt
# ================================================================

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime

app = FastAPI(title="Hermes GPS Backend")

# ── Cambia esta URL por la tuya de Render ──────────────────────
BASE_URL = "https://gps-backend-pqzg.onrender.com"
# ──────────────────────────────────────────────────────────────

STATIC_DIR   = "static"
FILES_DIR    = "static/files"
COMMAND_FILE = os.path.join(FILES_DIR, "command.json")
STATUS_FILE  = os.path.join(FILES_DIR, "status.json")

# Crear carpetas si no existen
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(FILES_DIR,  exist_ok=True)

# CORS abierto para que la web app pueda hacer fetch
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos estáticos (web app)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Servir archivos generados por el ESP32 (CSV, KML)
app.mount("/files",  StaticFiles(directory=FILES_DIR),  name="files")


# ── Helpers ────────────────────────────────────────────────────

def guardar_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def leer_json(path: str, default: dict) -> dict:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


# ── Rutas principales ──────────────────────────────────────────

@app.get("/")
def home():
    """Sirve la web app (index.html en static/)"""
    idx = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(idx):
        return FileResponse(idx, media_type="text/html")
    return JSONResponse({
        "status":  "Servidor Hermes GPS activo",
        "message": "Sube static/index.html para activar la web app"
    })


@app.get("/health")
def health():
    """Verificar estado del backend"""
    return {
        "status":        "ok",
        "service":       "Hermes GPS Backend",
        "version":       "2.0",
        "web":           BASE_URL,
        "index_existe":  os.path.isfile(os.path.join(STATIC_DIR, "index.html")),
        "timestamp_utc": datetime.utcnow().isoformat() + "Z"
    }


# ── Subir archivos desde el ESP32 ─────────────────────────────

@app.post("/upload/{filename}")
async def upload_file(filename: str, request: Request):
    """
    El ESP32 hace POST /upload/gps_log.csv con el cuerpo binario del archivo.
    También acepta /upload/ruta.kml, /upload/pending.csv, etc.
    """
    safe_name = os.path.basename(filename)   # evitar path traversal
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
        "status":   "ok",
        "filename": safe_name,
        "bytes":    len(body),
        "url":      f"{BASE_URL}/files/{safe_name}"
    }


# ── Comandos: Web App → ESP32 ──────────────────────────────────

@app.post("/command")
async def set_command(request: Request):
    """
    La web app hace POST /command con JSON:
    { "device": "HERMES-01", "cmd": "ciclo 10" }

    Comandos válidos:
      ciclo 5   → ciclo de 5 min
      ciclo 10  → ciclo de 10 min
      ciclo 15  → ciclo de 15 min
      ciclo 30  → ciclo de 30 min
      ciclo 60  → ciclo de 60 min
      status    → solicitar estado
      kml       → generar KML
      csv       → subir CSV
      reset     → reiniciar contadores
    """
    data   = await request.json()
    cmd    = str(data.get("cmd",    "none")).strip().lower()
    device = str(data.get("device", "HERMES-01")).strip()

    payload = {
        "status":     "pending",
        "device":     device,
        "cmd":        cmd,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    guardar_json(COMMAND_FILE, payload)
    return {"status": "ok", "message": "Comando guardado", "command": payload}


@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = False):
    """
    El ESP32 hace GET /command?device=HERMES-01&clear=true
    El parámetro clear=true borra el comando después de leerlo.
    """
    default = {"status": "none", "device": device, "cmd": "none"}
    data    = leer_json(COMMAND_FILE, default)

    # Si el comando es de otro dispositivo, devolver vacío
    if data.get("device", device) != device:
        return default

    # Limpiar comando después de leerlo
    if clear and data.get("cmd", "none") != "none":
        guardar_json(COMMAND_FILE, {
            "status":     "none",
            "device":     device,
            "cmd":        "none",
            "cleared_at": datetime.utcnow().isoformat() + "Z"
        })

    return data


# ── Estado del dispositivo: ESP32 → Web App ────────────────────

@app.post("/device-status")
async def set_device_status(request: Request):
    """
    El ESP32 hace POST /device-status con JSON:
    {
      "device": "HERMES-01",
      "estado": "NUEVA UBICACION",
      "despertar": 5,
      "ciclo_min": 5,
      "fallos_gps": 0,
      "lat": 4.825318,
      "lon": -74.352334,
      "fecha": "24/04/2025",
      "hora": "15:42:10",
      "bateria_v": 3.9,
      "bateria_pct": 72,
      "wifi": "conectado"
    }
    """
    data = await request.json()
    data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    guardar_json(STATUS_FILE, data)
    return {"status": "ok", "device_status": data}


@app.get("/device-status")
def get_device_status():
    """La web app hace GET /device-status para actualizar el panel"""
    return leer_json(STATUS_FILE, {
        "status":  "no_data",
        "message": "El ESP32 aún no ha enviado estado"
    })
