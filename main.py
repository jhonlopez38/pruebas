from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import os
import shutil

SECRET = "HERMES_SECRET_2025"

app = FastAPI()

UPLOAD_FOLDER = "static/files"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.mount("/files", StaticFiles(directory=UPLOAD_FOLDER), name="files")

engine = create_engine("sqlite:///gps.db")
Session = sessionmaker(bind=engine)
Base = declarative_base()

pwd = CryptContext(schemes=["bcrypt"])

security = HTTPBearer()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    password = Column(String)
    role = Column(String)

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    device_id = Column(String, unique=True)
    user_id = Column(Integer)

class GPSData(Base):
    __tablename__ = "gps"

    id = Column(Integer, primary_key=True)
    device_id = Column(String)
    estado = Column(String)
    lat = Column(Float)
    lon = Column(Float)
    bateria = Column(Float)

Base.metadata.create_all(engine)

class RegisterModel(BaseModel):
    name: str
    email: str
    password: str

class LoginModel(BaseModel):
    email: str
    password: str

class GPSModel(BaseModel):
    device: str
    estado: str
    lat: float
    lon: float
    bateria_v: float

def create_token(data):
    return jwt.encode(data, SECRET, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        return jwt.decode(token, SECRET, algorithms=["HS256"])
    except:
        raise HTTPException(401, "Token inválido")

@app.get("/")
def root():
    return {"status": "HERMES GPS ONLINE"}

@app.post("/register")
def register(data: RegisterModel):
    db = Session()

    exists = db.query(User).filter(User.email == data.email).first()

    if exists:
        raise HTTPException(400, "Usuario ya existe")

    user = User(
        name=data.name,
        email=data.email,
        password=pwd.hash(data.password),
        role="user"
    )

    db.add(user)
    db.commit()

    return {"ok": True}

@app.post("/login")
def login(data: LoginModel):
    db = Session()

    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(401, "Credenciales inválidas")

    if not pwd.verify(data.password, user.password):
        raise HTTPException(401, "Credenciales inválidas")

    token = create_token({
        "id": user.id,
        "email": user.email,
        "role": user.role
    })

    return {
        "token": token,
        "role": user.role
    }

@app.post("/device-status")
def device_status(data: GPSModel):
    db = Session()

    gps = GPSData(
        device_id=data.device,
        estado=data.estado,
        lat=data.lat,
        lon=data.lon,
        bateria=data.bateria_v
    )

    db.add(gps)
    db.commit()

    return {"ok": True}

@app.get("/devices")
def devices(user=Depends(verify_token)):
    db = Session()

    if user["role"] == "admin":
        devices = db.query(GPSData).all()
    else:
        user_devices = db.query(Device).filter(Device.user_id == user["id"]).all()

        ids = [d.device_id for d in user_devices]

        devices = db.query(GPSData).filter(GPSData.device_id.in_(ids)).all()

    return devices

@app.post("/assign-device")
def assign_device(device_id: str, user_id: int, user=Depends(verify_token)):
    if user["role"] != "admin":
        raise HTTPException(403, "Solo admin")

    db = Session()

    device = Device(
        device_id=device_id,
        user_id=user_id
    )

    db.add(device)
    db.commit()

    return {"ok": True}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "url": f"/files/{file.filename}"
    }
