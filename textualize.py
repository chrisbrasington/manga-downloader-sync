#!/usr/bin/env python3
from textual import events
from textual.app import App
from textual.widgets import Button

class MangaButton(Button):
    manga_title: str

    async def on_click(self, event: events.Click) -> None:
        """Called when the button is clicked."""
        print(f"Button {self.manga_title} clicked")


class MangaApp(App):
    """A simple app with manga buttons"""

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        # Create three buttons, each with a manga title
        titles = ["One Piece", "Naruto", "Bleach"]
        for title in titles:
            button = MangaButton(f"{title}") #, manga_title=title)
            # await self.view.dock(button)

if __name__ == "__main__":
    MangaApp().run()