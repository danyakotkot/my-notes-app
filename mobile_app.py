import flet as ft
import requests

# Локальна адреса сервера
API_URL = "http://192.168.0.122:8000" # Твій IP тут 

def main(page: ft.Page):
    page.title = "Мій Нотатник Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    
    # Список для нотаток
    notes_list = ft.ListView(expand=True, spacing=10)

    def load_notes(e=None):
        try:
            # Спроба отримати дані з сервера
            r = requests.get(f"{API_URL}/notes", timeout=2)
            notes_list.controls.clear()
            
            if r.status_code == 200:
                data = r.json()
                for n in data["notes"]:
                    # Додаємо просту картку з текстом
                    notes_list.controls.append(
                        ft.Container(
                            content=ft.Text(n["title"], size=18, weight="bold"),
                            padding=15,
                            bgcolor="#333333",
                            border_radius=10
                        )
                    )
            else:
                notes_list.controls.append(ft.Text("Помилка сервера", color="orange"))
            
            page.update()
            
        except Exception as ex:
            notes_list.controls.clear()
            notes_list.controls.append(ft.Text(f"Сервер офлайн (запусти run_app.py)", color="red"))
            page.update()

    # Створюємо кнопку без іконки (просто текст), щоб точно не було помилок
    refresh_btn = ft.ElevatedButton("Оновити список", on_click=load_notes)

    # Додаємо елементи на сторінку
    page.add(
        ft.Text("Мої Нотатки", size=25, weight="bold"),
        refresh_btn,
        notes_list
    )
    
    # Автоматичне завантаження при старті
    load_notes()

if __name__ == "__main__":
    # Спробуємо запустити як веб-сервер напряму
    ft.app(target=main, port=8080, host="0.0.0.0")
    