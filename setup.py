#!/usr/bin/env python3
import curses
import os

def read_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []

def write_file(filepath, lines):
    with open(filepath, 'w') as f:
        f.write("\n".join(lines) + "\n")

def main(stdscr):
    curses.curs_set(0)

    sources_file = "config/sources.txt"
    sync_file = "config/sync.txt"

    sources = read_file(sources_file)
    sync = set(read_file(sync_file))

    current_index = 0

    def display_menu():
        stdscr.clear()
        stdscr.addstr("Use SPACE to toggle sync, D to delete, A to add a new URL.\n")
        stdscr.addstr("Press Q to quit.\n\n")
        for idx, url in enumerate(sources):
            mark = "[x]" if url in sync else "[ ]"
            highlight = curses.A_REVERSE if idx == current_index else curses.A_NORMAL
            stdscr.addstr(f"{mark} {url}\n", highlight)
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
                write_file(sources_file, sources)
        elif key == ord('q'):
            break

if __name__ == "__main__":
    if not os.path.exists("config"):
        os.makedirs("config")
    curses.wrapper(main)
