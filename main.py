import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

SECRET_KEY = os.getenv("SECRET_KEY", "crossnotes-local-dev-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

database_url = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'notes.db'}"
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

connect_args = {}
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
elif "localhost" not in database_url and "127.0.0.1" not in database_url:
    connect_args = {"sslmode": "require"}

engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    notes = relationship("Note", back_populates="owner", cascade="all, delete-orphan")


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="", index=True)
    content = Column(Text, default="")
    is_pinned = Column(Boolean, default=False, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner = relationship("User", back_populates="notes")


def migrate_notes_table() -> None:
    inspector = inspect(engine)
    if "notes" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("notes")}
    is_sqlite = engine.url.drivername.startswith("sqlite")

    migrations = []
    if "is_pinned" not in existing_columns:
        migrations.append(
            "ALTER TABLE notes ADD COLUMN is_pinned BOOLEAN DEFAULT 0 NOT NULL"
            if is_sqlite
            else "ALTER TABLE notes ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE NOT NULL"
        )
    if "is_archived" not in existing_columns:
        migrations.append(
            "ALTER TABLE notes ADD COLUMN is_archived BOOLEAN DEFAULT 0 NOT NULL"
            if is_sqlite
            else "ALTER TABLE notes ADD COLUMN is_archived BOOLEAN DEFAULT FALSE NOT NULL"
        )
    if "created_at" not in existing_columns:
        migrations.append("ALTER TABLE notes ADD COLUMN created_at DATETIME" if is_sqlite else "ALTER TABLE notes ADD COLUMN created_at TIMESTAMP")
    if "updated_at" not in existing_columns:
        migrations.append("ALTER TABLE notes ADD COLUMN updated_at DATETIME" if is_sqlite else "ALTER TABLE notes ADD COLUMN updated_at TIMESTAMP")
    if "owner_id" not in existing_columns:
        migrations.append("ALTER TABLE notes ADD COLUMN owner_id INTEGER")

    with engine.begin() as connection:
        for migration in migrations:
            connection.execute(text(migration))
        connection.execute(text("UPDATE notes SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        connection.execute(text("UPDATE notes SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        connection.execute(
            text(
                """
                UPDATE notes
                SET owner_id = (SELECT id FROM users ORDER BY id LIMIT 1)
                WHERE owner_id IS NULL AND EXISTS (SELECT 1 FROM users)
                """
            )
        )


Base.metadata.create_all(bind=engine)
migrate_notes_table()

app = FastAPI(title="CrossNotes")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserAuth(BaseModel):
    username: str
    password: str


class NotePayload(BaseModel):
    title: str = ""
    content: str = ""
    is_pinned: bool = False
    is_archived: bool = False


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_error
    return user


def get_owned_note(note_id: int, user: User, db: Session) -> Note:
    note = db.query(Note).filter(Note.id == note_id, Note.owner_id == user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


def serialize_note(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title or "",
        "content": note.content or "",
        "is_pinned": bool(note.is_pinned),
        "is_archived": bool(note.is_archived),
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


@app.post("/register")
def register(user: UserAuth, db: Session = Depends(get_db)):
    username = user.username.strip()
    if len(username) < 3 or len(user.password) < 4:
        raise HTTPException(status_code=400, detail="Логін має бути від 3 символів, пароль від 4.")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Такий логін уже зайнятий.")

    db_user = User(username=username, hashed_password=pwd_context.hash(user.password))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    db.query(Note).filter(Note.owner_id.is_(None)).update({Note.owner_id: db_user.id}, synchronize_session=False)
    db.commit()
    return {"message": "User created"}


@app.post("/token")
async def login(user: UserAuth, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username.strip()).first()
    if not db_user or not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Неправильний логін або пароль.")

    access_token = create_access_token(data={"sub": db_user.username})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/notes", response_model=dict)
def get_notes(
    archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notes = (
        db.query(Note)
        .filter(Note.owner_id == current_user.id, Note.is_archived == archived)
        .order_by(Note.is_pinned.desc(), Note.updated_at.desc(), Note.id.desc())
        .all()
    )
    return {"notes": [serialize_note(note) for note in notes]}


@app.get("/notes/{note_id}")
def get_note(note_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return serialize_note(get_owned_note(note_id, current_user, db))


@app.post("/notes")
def add_note(note: NotePayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    db_note = Note(
        title=note.title.strip() or "Без назви",
        content=note.content,
        is_pinned=note.is_pinned,
        is_archived=note.is_archived,
        created_at=now,
        updated_at=now,
        owner_id=current_user.id,
    )
    db.add(db_note)
    db.commit()
    db.refresh(db_note)
    return serialize_note(db_note)


@app.put("/notes/{note_id}")
def update_note(
    note_id: int,
    note_data: NotePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_note = get_owned_note(note_id, current_user, db)
    db_note.title = note_data.title.strip() or "Без назви"
    db_note.content = note_data.content
    db_note.is_pinned = note_data.is_pinned
    db_note.is_archived = note_data.is_archived
    db_note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_note)
    return serialize_note(db_note)


@app.delete("/notes/{note_id}")
def delete_note(note_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = get_owned_note(note_id, current_user, db)
    db.delete(note)
    db.commit()
    return {"status": "ok"}


@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Можна завантажувати тільки зображення.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        suffix = ".png"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{current_user.id}-{uuid.uuid4().hex}{suffix}"
    upload_path = UPLOAD_DIR / filename

    with upload_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"url": f"/static/uploads/{filename}"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/manifest.json")
async def get_manifest():
    manifest = STATIC_DIR / "manifest.json"
    if manifest.exists():
        return FileResponse(manifest)
    return FileResponse(BASE_DIR / "manifest.json")


@app.get("/")
async def read_index():
    return FileResponse(BASE_DIR / "index.html")
