from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os

app = FastAPI(title="Hermes GPS Backend")

BASE_URL = "https://gps-backend-pqzg.onrender.com"

STATIC_FOLDER = "static"
FILES_FOLDER = "static/files"

os.makedirs(STATIC_FOLDER, exist_ok=True)
os.makedirs(FILES_FOLDER, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_FOLDER), name="static")
app.mount("/files", StaticFiles(directory=FILES_FOLDER), name="files")


@app.get("/")
def home():
    index_path = os.path.join(STATIC_FOLDER, "index.html")

    if os.path.exists(index_path):
        return FileResponse(index_path)

    return {
        "status": "Servidor Hermes GPS activo",
        "message": "Web app no instalada todavía",
        "health": f"{BASE_URL}/health",
        "links": f"{BASE_URL}/links",
        "files": {
            "kml": f"{BASE_URL}/files/ruta.kml",
            "csv": f"{BASE_URL}/files/gps_log.csv"
        }
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "Hermes GPS Backend",
        "web": BASE_URL
    }


@app.get("/links")
def links():
    return {
        "web": BASE_URL,
        "health": f"{BASE_URL}/health",
        "kml": f"{BASE_URL}/files/ruta.kml",
        "csv": f"{BASE_URL}/files/gps_log.csv"
    }


@app.get("/last")
def last_files():
    kml_path = os.path.join(FILES_FOLDER, "ruta.kml")
    csv_path = os.path.join(FILES_FOLDER, "gps_log.csv")

    return {
        "kml": {
            "exists": os.path.exists(kml_path),
            "url": f"{BASE_URL}/files/ruta.kml"
        },
        "csv": {
            "exists": os.path.exists(csv_path),
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
            content={
                "status": "error",
                "message": "Archivo vacío"
            }
        )

    with open(file_path, "wb") as f:
        f.write(data)

    return {
        "status": "ok",
        "filename": safe_name,
        "url": f"{BASE_URL}/files/{safe_name}"
    }
