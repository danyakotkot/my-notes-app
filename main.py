from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "notes.db"

# Функція для ініціалізації бази даних
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Створюємо таблицю, якщо її ще немає
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

class Note(BaseModel):
    title: str
    content: str

# 1. Отримати всі нотатки
@app.get("/notes")
def get_notes():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, content FROM notes")
    rows = cursor.fetchall()
    conn.close()
    
    notes = [{"id": r[0], "title": r[1], "content": r[2]} for r in rows]
    return {"notes": notes}

# 2. Створити або оновити нотатку
@app.post("/notes")
def create_note(note: Note):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Якщо нотатка з такою назвою є — оновлюємо, якщо ні — створюємо
    cursor.execute("SELECT id FROM notes WHERE title = ?", (note.title,))
    exists = cursor.fetchone()
    
    if exists:
        cursor.execute("UPDATE notes SET content = ? WHERE title = ?", (note.content, note.title))
    else:
        cursor.execute("INSERT INTO notes (title, content) VALUES (?, ?)", (note.title, note.content))
    
    conn.commit()
    conn.close()
    return {"status": "success"}

# 3. Видалити нотатку за назвою (для простоти поки так)
@app.delete("/notes/{title}")
def delete_note(title: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notes WHERE title = ?", (title,))
    conn.commit()
    conn.close()
    return {"status": "success"}