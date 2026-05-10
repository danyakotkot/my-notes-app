import webview
import uvicorn
import threading
import os
import sys
import time
from main import app # Імпортуємо наш сервер з файлу main.py

# Функція для пошуку шляху до файлів всередині .exe
def resource_path(relative_path):
    try:
        # PyInstaller створює тимчасову папку _MEIxxxx
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Функція для фонового запуску сервера
def start_server():
    # log_level="critical" прибирає зайвий текст із терміналу
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == '__main__':
    print("Запускаємо Нотатник...")
    
    # 1. Запускаємо бекенд (сервер) в окремому потоці, щоб він не блокував вікно
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Даємо серверу пів секунди на запуск, щоб інтерфейс не видав помилку
    time.sleep(0.5)

    # 2. Формуємо шлях до нашого HTML-файлу
html_path = "http://127.0.0.1:8000"

    # 3. Створюємо вікно програми
window = webview.create_window('Мій Нотатник', html_path)

    # 4. Запускаємо вікно!
webview.start()