import flet as ft
import requests

# Замінимо це на URL твого сервера пізніше
API_URL = "http://127.0.0.1:8000" 

def main(page: ft.Page):
    page.title = "Мій Нотатник Mobile"
    page.theme_mode = ft.ThemeMode.DARK # Відразу робимо темну тему
    
    notes_list = ft.ListView(expand=True, spacing=10, padding=20)

    def load_notes():
        try:
            response = requests.get(f"{API_URL}/notes")
            data = response.json()
            notes_list.controls.clear()
            for note in data["notes"]:
                notes_list.controls.add(
                    ft.ListTile(
                        title=ft.Text(note["title"]),
                        subtitle=ft.Text(note["content"][:50] + "..."),
                        on_click=lambda _: print(f"Відкрито: {note['title']}")
                    )
                )
            page.update()
        except:
            notes_list.controls.add(ft.Text("Помилка підключення до сервера"))
            page.update()

    # Кнопка оновлення
    page.add(
        ft.AppBar(title=ft.Text("Мої Нотатки"), bgcolor=ft.Colors.SURFACE_VARIANT),
        notes_list,
        ft.FloatingActionButton(icon=ft.Icons.REFRESH, on_click=lambda _: load_notes())
    )
    
    load_notes()

ft.app(target=main)