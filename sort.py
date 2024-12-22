#!/usr/bin/env python3
import curses
import os, re
import sys
import argparse
import textwrap
from classes.parser import Utility  # Assuming Utility is imported from parser

# Configuration for easy modification
ITEMS_PER_PAGE = 70
SOURCES_FILE = "config/sources.txt"

def read_file(filepath):
    """Reads a file and returns a list of non-empty lines."""
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []

def write_file(filepath, lines):
    """Writes a list of lines to a file."""
    with open(filepath, 'w') as f:
        f.write("\n".join(lines) + "\n")

    # Remove last empty line
    with open(filepath, 'rb+') as f:
        f.seek(-1, os.SEEK_END)
        f.truncate()

def display_menu(stdscr, sources, current_page, current_index):
    """Displays the menu with the sync list, including sort numbers and pagination."""
    max_y, max_x = stdscr.getmaxyx()
    visible_lines = max_y - 6  # Number of lines we can display, leaving room for other UI elements

    start_index = current_page * ITEMS_PER_PAGE
    end_index = min((current_page + 1) * ITEMS_PER_PAGE, len(sources))

    total_pages = (len(sources) // ITEMS_PER_PAGE) + (1 if len(sources) % ITEMS_PER_PAGE > 0 else 0)
    stdscr.clear()
    stdscr.addstr(f"Page [{current_page + 1} of {total_pages}]\n\n")
    stdscr.addstr("Use arrow keys to navigate, type a number to change the sort order, and press Enter to confirm.\n")
    stdscr.addstr("Press Q to quit, 'i' to view details.\n\n")

    for idx in range(start_index, end_index):
        url, sync_flag = sources[idx].split(",")
        highlight = curses.A_REVERSE if idx == start_index + current_index else curses.A_NORMAL
        sort_number = idx + 1

        # Remove white spaces from sync flag
        sync_flag = sync_flag.strip()

        wrapped_url = textwrap.fill(url, width=max_x - 5)

        # Display whether the URL is synced or not
        is_synced = "[x]" if sync_flag == "1" else "[ ]"
        stdscr.addstr(f"{sort_number}. {is_synced} {wrapped_url}\n", highlight)

    stdscr.refresh()

def show_popup(stdscr, title, detail_text):
    """Displays a popup window with the provided detail text."""
    max_y, max_x = stdscr.getmaxyx()
    popup_height = max_y // 2
    popup_width = max_x // 2
    popup_start_y = (max_y - popup_height) // 2
    popup_start_x = (max_x - popup_width) // 2

    popup_win = curses.newwin(popup_height, popup_width, popup_start_y, popup_start_x)
    popup_win.border()

    # Ensure proper line breaks for detail_text
    wrapped_text = textwrap.fill(detail_text, width=popup_width - 4)
    text_lines = wrapped_text.split("\n")

    popup_win.addstr(1, 2, title[:popup_width - 4])  # Display title truncated to fit

    for idx, line in enumerate(text_lines[:popup_height - 3]):
        popup_win.addstr(2 + idx, 2, line[:popup_width - 4])

    popup_win.refresh()

    while True:
        key = popup_win.getch()
        if key in (ord('i'), 27):  # Close on 'i' or ESC
            break

    stdscr.touchwin()
    stdscr.refresh()

def main(stdscr):
    curses.curs_set(0)

    sources = read_file(SOURCES_FILE)

    current_page = 0
    current_index = 0

    while True:
        display_menu(stdscr, sources, current_page, current_index)

        key = stdscr.getch()

        if key == curses.KEY_DOWN and current_index < ITEMS_PER_PAGE - 1:
            current_index += 1
        elif key == curses.KEY_DOWN and current_index == ITEMS_PER_PAGE - 1:
            if (current_page + 1) * ITEMS_PER_PAGE < len(sources):
                current_page += 1
                current_index = 0

        elif key == curses.KEY_UP and current_index > 0:
            current_index -= 1
        elif key == curses.KEY_UP and current_index == 0 and current_page > 0:
            current_page -= 1
            current_index = ITEMS_PER_PAGE - 1

        elif key == curses.KEY_RIGHT and (current_page + 1) * ITEMS_PER_PAGE < len(sources):
            current_page += 1
            current_index = 0

        elif key == curses.KEY_LEFT and current_page > 0:
            current_page -= 1
            current_index = 0

        elif key == ord('i'):
            url, _ = sources[current_page * ITEMS_PER_PAGE + current_index].split(",")
            utility = Utility()
            try:
                manga = utility.get_manga(url)
                detail_text = f"{manga.desc.strip()}"

                # remove [*](*) hyperlinks from detail_text using regex inline not utility
                detail_text = re.sub(r'\[.*?\]\(.*?\)', '', detail_text)
                detail_text = detail_text.replace('\n\n', '\n')
                detail_text = detail_text.replace('___', '')

                # add status
                detail_text += f"\n\nStatus: {manga.status}"

                genres = [tag['attributes']['name']['en'] for tag in manga.data['attributes']['tags'] if tag['attributes']['group'] == 'genre']

                # add genres
                detail_text += f"\n\nGenres: {', '.join(genres)}"

                show_popup(stdscr, manga.title, detail_text)
            except Exception as e:
                show_popup(stdscr, "Error", str(e))

        # q or escape
        elif key == ord('q') or key == 27:
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sort and display manga URLs with optional details.")
    args = parser.parse_args()

    if not os.path.exists("config"):
        os.makedirs("config")

    if ITEMS_PER_PAGE > os.get_terminal_size().lines - 10:
        ITEMS_PER_PAGE = os.get_terminal_size().lines - 10

    curses.wrapper(main)
