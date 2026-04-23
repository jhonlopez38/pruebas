from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

UPLOAD_FOLDER = "static/files"
BASE_URL = "https://gps-backend-pqzg.onrender.com"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.mount("/files", StaticFiles(directory=UPLOAD_FOLDER), name="files")

@app.get("/")
def root():
    return {"status": "Servidor GPS activo"}

@app.post("/upload/{filename}")
async def upload_file(filename: str, request: Request):
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    data = await request.body()

    with open(file_path, "wb") as f:
        f.write(data)

    return {
        "status": "ok",
        "filename": filename,
        "url": f"{BASE_URL}/files/{filename}"
    }
