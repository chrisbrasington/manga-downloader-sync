#!/usr/bin/env python3
import curses
import os
import re
from classes.parser import Utility

def read_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []

def write_file(filepath, lines):
    with open(filepath, 'w') as f:
        f.write("\n".join(lines) + "\n")

def get_manga_details(url):
    try:
        utility = Utility()
        manga = utility.get_manga(url)

        english_title = manga.get_english_title()
        resulting_title = manga.title

        if english_title != manga.title:
            resulting_title = f'{english_title} ({manga.title})'

        return resulting_title, manga.desc, manga
    except Exception as e:
        return "Unknown Title", f"Error fetching details: {str(e)}", None

def clean_text(text):
    # Remove unwanted special characters (e.g., control characters, excessive spaces)
    text = re.sub(r'[^\x00-\x7F]+', '', text)  # Remove non-ASCII characters
    text = re.sub(r'\s+', ' ', text).strip()  # Replace multiple spaces with a single space and strip leading/trailing spaces
    return text

def wrap_text(text, width, indent):
    text = clean_text(text)  # Clean the description first
    lines = []
    while text:
        if len(text) <= width:
            lines.append(text)
            break
        split_at = text.rfind(' ', 0, width)
        if split_at == -1:
            split_at = width
        lines.append(text[:split_at])
        text = text[split_at:].strip()
    return [(indent + line) for line in lines]

def main(stdscr):
    curses.curs_set(0)

    sources_file = "config/sources.txt"
    sync_file = "config/sync.txt"

    sources = read_file(sources_file)
    sync = set(read_file(sync_file))

    manga_details = {url: get_manga_details(url) for url in sources}

    current_index = 0

    def display_menu():
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()  # Get the screen size (height and width)
        num_visible = max_y - 5  # Allow for the header and spacing
        start_index = max(0, current_index - num_visible // 2)  # Center the selection if possible

        try:
            stdscr.addstr("Use SPACE to toggle sync, D to delete, A to add a new URL.\n")
            stdscr.addstr("Press Q to quit.\n\n")

            for idx in range(start_index, min(start_index + num_visible, len(sources))):
                url = sources[idx]
                mark = "[x]" if url in sync else "[ ]"
                highlight = curses.A_REVERSE if idx == current_index else curses.A_NORMAL
                title, desc, manga = manga_details.get(url, ("Unknown Title", "", None))
                stdscr.addstr(f"{mark} {url}\n", highlight)
                stdscr.addstr(f"   Title: {title}\n", highlight)

                if manga and hasattr(manga, "status"):
                    stdscr.addstr(f"     Status: {manga.status}\n", highlight)

                if desc:
                    wrapped_desc = wrap_text(desc, max_x - 6, "     ")
                    for line in wrapped_desc:
                        stdscr.addstr(f"{line}\n", highlight)
                stdscr.addstr("\n")
        except curses.error:
            pass  # Continue if there are issues with the screen size or rendering

        stdscr.refresh()

    while True:
        display_menu()
        key = stdscr.getch()

        if key == curses.KEY_UP and current_index > 0:
            current_index -= 1
        elif key == curses.KEY_DOWN and current_index < len(sources) - 1:
            current_index += 1
        elif key == ord(' '):
            url = sources[current_index]
            if url in sync:
                sync.remove(url)
            else:
                sync.add(url)
            write_file(sync_file, list(sync))
        elif key == ord('d'):
            url = sources.pop(current_index)
            sync.discard(url)
            manga_details.pop(url, None)
            write_file(sources_file, sources)
            write_file(sync_file, list(sync))
            current_index = min(current_index, len(sources) - 1)
        elif key == ord('a'):
            curses.echo()
            stdscr.addstr(len(sources) + 3, 0, "Enter new URL: ")
            new_url = stdscr.getstr().decode("utf-8").strip()
            curses.noecho()
            if new_url and new_url not in sources:
                sources.append(new_url)
                manga_details[new_url] = get_manga_details(new_url)
                write_file(sources_file, sources)
        elif key == ord('q'):
            break

if __name__ == "__main__":
    if not os.path.exists("config"):
        os.makedirs("config")
    curses.wrapper(main)
