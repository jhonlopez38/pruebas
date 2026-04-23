from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
import os
import shutil

app = FastAPI()

# Carpeta donde se guardan archivos
UPLOAD_FOLDER = "static/files"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Montar carpeta para acceso público
app.mount("/files", StaticFiles(directory=UPLOAD_FOLDER), name="files")

# URL de tu backend en Render
BASE_URL = "https://gps-backend-pqzg.onrender.com"

# Ruta de prueba
@app.get("/")
def root():
    return {"status": "Servidor GPS activo"}

# Subir archivo y devolver link
@app.post("/upload/{filename}")
async def upload_file(filename: str, file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "status": "ok",
        "url": f"{BASE_URL}/files/{filename}"
    }
