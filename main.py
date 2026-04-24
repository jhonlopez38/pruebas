#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <TinyGPSPlus.h>
#include <HardwareSerial.h>
#include <Preferences.h>
#include <esp_sleep.h>
#include <LittleFS.h>
#include <time.h>

// WIFI
const char* ssid = "POCO F6";
const char* password = "123456780";

// TELEGRAM
String botToken = "PEGA_AQUI_TU_TOKEN";
String chatID = "866739056";

// BACKEND
String backendBaseURL = "https://gps-backend-pqzg.onrender.com";

// GPS
TinyGPSPlus gps;
HardwareSerial gpsSerial(2);
const int GPS_RX = 16;
const int GPS_TX = 17;

// BATERIA
#define ENABLE_BATTERY_READING false
const int BATTERY_ADC_PIN = 34;
const float ADC_REF = 3.3;
const int ADC_RESOLUTION = 4095;
const float VOLTAGE_DIVIDER_RATIO = 2.0;

// TIEMPOS
const unsigned long GPS_TIM…
[3:29 p.m., 24/4/2026] J.J: from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from datetime import datetime

app = FastAPI(title="Hermes GPS Backend")

BASE_URL = "https://gps-backend-pqzg.onrender.com"

STATIC_FOLDER = "static"
FILES_FOLDER = "static/files"

COMMAND_FILE = os.path.join(FILES_FOLDER, "command.json")
STATUS_FILE = os.path.join(FILES_FOLDER, "status.json")

os.makedirs(STATIC_FOLDER, exist_ok=True)
os.makedirs(FILES_FOLDER, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_FOLDER), name="static")
app.mount("/files", StaticFiles(directory=FILES_FOLDER), name="files")


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


@app.get("/")
def home():
    index_path = os.path.join(STATIC_FOLDER, "index.html")

    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")

    return JSONResponse({
        "status": "Servidor Hermes GPS activo",
        "message": "No se encontró static/index.html",
        "expected_file": "static/index.html",
        "health": f"{BASE_URL}/health",
        "files": {
            "kml": f"{BASE_URL}/files/ruta.kml",
            "csv": f"{BASE_URL}/files/gps_log.csv"
        }
    })


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "Hermes GPS Backend",
        "web": BASE_URL,
        "index_exists": os.path.isfile(os.path.join(STATIC_FOLDER, "index.html")),
        "files_folder_exists": os.path.isdir(FILES_FOLDER)
    }


@app.get("/links")
def links():
    return {
        "web": BASE_URL,
        "health": f"{BASE_URL}/health",
        "kml": f"{BASE_URL}/files/ruta.kml",
        "csv": f"{BASE_URL}/files/gps_log.csv",
        "command": f"{BASE_URL}/command",
        "device_status": f"{BASE_URL}/device-status"
    }


@app.get("/last")
def last_files():
    kml_path = os.path.join(FILES_FOLDER, "ruta.kml")
    csv_path = os.path.join(FILES_FOLDER, "gps_log.csv")

    return {
        "kml": {
            "exists": os.path.isfile(kml_path),
            "url": f"{BASE_URL}/files/ruta.kml"
        },
        "csv": {
            "exists": os.path.isfile(csv_path),
            "url": f"{BASE_URL}/files/gps_log.csv"
        }
    }


@app.post("/upload/{filename}")
async def upload_file(filename: str, request: Request):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(FILES_FOLDER, safe_name)

    data = await request.body()

    if not data:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Archivo vacío"}
        )

    with open(file_path, "wb") as f:
        f.write(data)

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
        "created_at": datetime.utcnow().isoformat() + "Z"
    }

    save_json(COMMAND_FILE, payload)

    return {
        "status": "ok",
        "message": "Comando guardado",
        "command": payload
    }


@app.get("/command")
def get_command(device: str = "HERMES-01", clear: bool = True):
    default = {
        "status": "none",
        "device": device,
        "cmd": "none"
    }

    data = load_json(COMMAND_FILE, default)

    if data.get("device", device) != device:
        return default

    if clear and data.get("cmd", "none") != "none":
        save_json(COMMAND_FILE, {
            "status": "none",
            "device": device,
            "cmd": "none",
            "cleared_at": datetime.utcnow().isoformat() + "Z"
        })

    return data


@app.post("/device-status")
async def set_device_status(request: Request):
    data = await request.json()
    data["updated_at"] = datetime.utcnow().isoformat() + "Z"

    save_json(STATUS_FILE, data)

    return {
        "status": "ok",
        "device_status": data
    }


@app.get("/device-status")
def get_device_status():
    return load_json(STATUS_FILE, {
        "status": "no_data",
        "message": "El ESP32 aún no ha enviado estado"
    })
