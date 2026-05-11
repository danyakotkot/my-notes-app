import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from passlib.context import CryptContext
from jose import JWTError, jwt
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import UploadFile, File
import shutil


# Налаштування безпеки
SECRET_KEY = os.getenv("SECRET_KEY", "дуже-секретний-дефолтний-ключ")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # Токен на тиждень

# Замість ["bcrypt"] використовуємо "pbkdf2_sha256"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# 1. Отримуємо URL бази даних з налаштувань Render
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# Render іноді дає префікс postgres://, але SQLAlchemy вимагає postgresql://
if SQLALCHEMY_DATABASE_URL and SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Створюємо двигун з підтримкою SSL (обов'язково для Render)
# check_same_thread потрібен тільки для SQLite, для Postgres його видаляємо
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"sslmode": "require"} if SQLALCHEMY_DATABASE_URL and "localhost" not in SQLALCHEMY_DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    # Ця команда створить таблиці в PostgreSQL автоматично
    Base.metadata.create_all(bind=engine)

# Моделі БД
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    notes = relationship("Note", back_populates="owner")

class Note(Base):
    __tablename__ = "notes"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    content = Column(Text)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="notes")

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Допоміжні функції
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise HTTPException(status_code=401)
    except JWTError: raise HTTPException(status_code=401)
    user = db.query(User).filter(User.username == username).first()
    if user is None: raise HTTPException(status_code=401)
    return user

# Додай цей клас перед маршрутами
class UserAuth(BaseModel):
    username: str
    password: str

@app.post("/register")
def register(user: UserAuth, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user: raise HTTPException(status_code=400, detail="Username taken")
    
    # Використовуємо pbkdf2_sha256 через наш pwd_context
    hashed_pwd = pwd_context.hash(str(user.password))
    
    new_user = User(username=user.username, hashed_password=hashed_pwd)
    db.add(new_user)
    db.commit()
    return {"msg": "User created"}

@app.post("/token")
async def login(user: UserAuth, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    
    # Перевірка через pbkdf2_sha256
    if not db_user or not pwd_context.verify(str(user.password), db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Wrong username or password")
    
    access_token = create_access_token(data={"sub": db_user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# Маршрути Нотаток
@app.get("/notes")
def get_notes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"notes": db.query(Note).filter(Note.owner_id == current_user.id).all()}

class NoteCreate(BaseModel):
    title: str
    content: str

@app.post("/notes")
def add_note(note: NoteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_note = Note(title=note.title, content=note.content, owner_id=current_user.id)
    db.add(db_note)
    db.commit()
    return {"status": "ok"}

@app.put("/notes/{note_id}")
def update_note(
    note_id: int, 
    note_data: NoteCreate, 
    db: Session = Depends(get_db), 
    current_user = Depends(get_current_user)
):
    print(f"Updating note {note_id} for user {current_user.id}")

    # Шукаємо нотатку саме цього користувача
    db_note = db.query(Note).filter(Note.id == note_id, Note.owner_id == current_user.id).first()
    
    if not db_note:
        print("Note not found!")
        raise HTTPException(status_code=404, detail="Нотатку не знайдено")

    # Оновлюємо дані
    db_note.title = note_data.title
    db_note.content = note_data.content
    
    try:
        db.commit()
        db.refresh(db_note)
        return db_note
    except Exception as e:
        db.rollback()
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail="Database update failed")

@app.delete("/notes/{note_id}")
def delete_note(note_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == current_user.id).first()
    if note:
        db.delete(note)
        db.commit()
    return {"status": "ok"}

@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    # На Render краще зберігати фото у хмарі (наприклад, Cloudinary), 
    # але для тесту створимо папку uploads
    upload_path = f"static/uploads/{file.filename}"
    os.makedirs("static/uploads", exist_ok=True)
    
    with open(upload_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"url": f"/static/uploads/{file.filename}"}

# Статика та PWA
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse("static/manifest.json")

@app.get("/")
async def read_index():
    return FileResponse('index.html')