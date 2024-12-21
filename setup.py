#!/usr/bin/env python3
import curses
import os
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
        # return manga, manga.desc

        english_title = manga.get_english_title()
        resulting_title = manga.title

        if english_title is not manga.title:
            resulting_title = f'{english_title} ({manga.title})'

        return resulting_title, manga.desc, manga
    except Exception as e:
        return "Unknown Title", "Failed to fetch details"

def wrap_text(text, width, indent):
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
        stdscr.addstr("Use SPACE to toggle sync, D to delete, A to add a new URL.\n")
        stdscr.addstr("Press Q to quit.\n\n")
        for idx, url in enumerate(sources):
            mark = "[x]" if url in sync else "[ ]"
            highlight = curses.A_REVERSE if idx == current_index else curses.A_NORMAL
            title, desc, manga = manga_details.get(url, ("Unknown Title", ""))
            stdscr.addstr(f"{mark} {url}\n", highlight)
            stdscr.addstr(f"   {title}\n", highlight)

            # status
            stdscr.addstr(f"     Status: {manga.status}\n", highlight)

            if desc:
                stdscr.addstr("\n")
                wrapped_desc = wrap_text(desc, curses.COLS - 4, "     ")
                for line in wrapped_desc:
                    stdscr.addstr(f"{line}\n", highlight)
            stdscr.addstr("\n")
        stdscr.refresh()

    while True:
        display_menu()
        key = stdscr.getch()

        if key == curses.KEY_UP and current_index > 0:
            current_index -= 1
        elif key == curses.KEY_DOWN and current_index < len(sources) - 1:
            current_index += 1
        elif key == ord(' '):
            # Toggle sync
            url = sources[current_index]
            if url in sync:
                sync.remove(url)
            else:
                sync.add(url)
            write_file(sync_file, list(sync))
        elif key == ord('d'):
            # Delete URL
            url = sources.pop(current_index)
            sync.discard(url)
            manga_details.pop(url, None)
            write_file(sources_file, sources)
            write_file(sync_file, list(sync))
            current_index = min(current_index, len(sources) - 1)
        elif key == ord('a'):
            # Add a new URL
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
