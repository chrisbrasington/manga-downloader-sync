#!/usr/bin/env python3
import curses
import os
import re
from classes.parser import Utility
import threading

# Configuration at the top for easy modification
ITEMS_PER_PAGE = 5

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

    manga_details = {}
    current_page = 0  # Keep track of the current page
    current_index = 0  # Keep track of the index of the current item being viewed
    max_y, max_x = stdscr.getmaxyx()  # Get the screen size (height and width)
    visible_lines = max_y - 6  # Number of lines we can display minus the header

    def display_menu():
        nonlocal current_page, current_index
        try:
            stdscr.clear()

            # Display the page information
            total_pages = (len(sources) // ITEMS_PER_PAGE) + (1 if len(sources) % ITEMS_PER_PAGE > 0 else 0)
            stdscr.addstr(f"Page [{current_page + 1} of {total_pages}]\n\n")

            stdscr.addstr("Use SPACE to toggle sync, D to delete, A to add a new URL.\n")
            stdscr.addstr("Press Q to quit.\n\n")

            # Display "Loading..." until manga details are fetched
            start_index = current_page * ITEMS_PER_PAGE
            end_index = min((current_page + 1) * ITEMS_PER_PAGE, len(sources))

            for idx in range(start_index, end_index):
                url = sources[idx]
                mark = "[x]" if url in sync else "[ ]"
                highlight = curses.A_REVERSE if idx == start_index + current_index else curses.A_NORMAL
                title, desc, manga = manga_details.get(url, ("Loading...", "", None))
                
                stdscr.addstr(f"{mark} {url}\n", highlight)
                stdscr.addstr(f"   Title: {title}\n", highlight)

                if manga and hasattr(manga, "status"):
                    stdscr.addstr(f"     Status: {manga.status}\n", highlight)

                if desc:
                    wrapped_desc = wrap_text(desc, max_x - 6, "     ")
                    for line in wrapped_desc:
                        stdscr.addstr(f"{line}\n", highlight)

            stdscr.refresh()
        except curses.error:
            pass  # If there's an error with the curses library (e.g., printing too many lines), just continue

    def load_manga_details(url):
        if url not in manga_details:
            manga_details[url] = get_manga_details(url)

    def preload_next_page():
        # Preload manga details for the next page in the background
        next_page = current_page + 1
        if next_page * ITEMS_PER_PAGE < len(sources):
            start_index = next_page * ITEMS_PER_PAGE
            end_index = min((next_page + 1) * ITEMS_PER_PAGE, len(sources))
            for idx in range(start_index, end_index):
                url = sources[idx]
                if url not in manga_details:
                    load_manga_details(url)

    while True:
        display_menu()

        # Start loading manga details for the current page
        start_index = current_page * ITEMS_PER_PAGE
        end_index = min((current_page + 1) * ITEMS_PER_PAGE, len(sources))

        for idx in range(start_index, end_index):
            url = sources[idx]
            load_manga_details(url)

        # Preload manga details for the next page in the background
        threading.Thread(target=preload_next_page, daemon=True).start()

        key = stdscr.getch()

        if key == curses.KEY_DOWN and current_index < ITEMS_PER_PAGE - 1:
            current_index += 1
        elif key == curses.KEY_DOWN and current_index == ITEMS_PER_PAGE - 1:
            if (current_page + 1) * ITEMS_PER_PAGE < len(sources):
                current_page += 1
            current_index = 0  # Reset index to top when moving to the next page

        elif key == curses.KEY_UP and current_index > 0:
            current_index -= 1
        elif key == curses.KEY_UP and current_index == 0 and current_page > 0:
            current_page -= 1
            current_index = ITEMS_PER_PAGE - 1  # Set index to the last item of the previous page

        try:
            if key == ord(' '):
                url = sources[current_page * ITEMS_PER_PAGE + current_index]
                if url in sync:
                    sync.remove(url)
                else:
                    sync.add(url)
                write_file(sync_file, list(sync))
            elif key == ord('d'):
                url = sources.pop(current_page * ITEMS_PER_PAGE + current_index)  # Remove current item
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
        except Exception as e:
            stdscr.addstr(f"\nError: {str(e)}")
            stdscr.refresh()
            curses.napms(2000)  # Wait for 2 seconds to display error before continuing

if __name__ == "__main__":
    if not os.path.exists("config"):
        os.makedirs("config")
    curses.wrapper(main)
