from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
import os
import shutil

app = FastAPI()

UPLOAD_FOLDER = "static/files"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.mount("/files", StaticFiles(directory=UPLOAD_FOLDER), name="files")

@app.get("/")
def root():
    return {"status": "Servidor GPS activo"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    url = f"https://TU_APP.onrender.com/files/{file.filename}"

    return {"url": url}