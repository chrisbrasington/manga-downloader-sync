#!/usr/bin/env python3
import curses
import os
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

    # remove last empty line
    with open(filepath, 'rb+') as f:
        f.seek(-1, os.SEEK_END)
        f.truncate()

def display_menu(stdscr, sources, current_page, current_index):
    """Displays the menu with the sync list, including sort numbers and pagination."""
    max_y, max_x = stdscr.getmaxyx()

    start_index = current_page * ITEMS_PER_PAGE
    end_index = min((current_page + 1) * ITEMS_PER_PAGE, len(sources))

    total_pages = (len(sources) // ITEMS_PER_PAGE) + (1 if len(sources) % ITEMS_PER_PAGE > 0 else 0)
    stdscr.clear()
    stdscr.addstr(f"Page [{current_page + 1} of {total_pages}]\n\n")
    stdscr.addstr("Use arrow keys to navigate pages, type a number to change the sort order, and press Enter to confirm.\n")
    stdscr.addstr("Press Q to quit.\n\n")

    for idx in range(start_index, end_index):
        url, sync_flag = sources[idx].split(",")
        highlight = curses.A_REVERSE if idx == start_index + current_index else curses.A_NORMAL
        sort_number = idx + 1

        # remove white spaces from sync flag
        sync_flag = sync_flag.strip()

        wrapped_url = textwrap.fill(url, width=max_x - 5)

        # Display whether the URL is synced or not
        is_synced = "[x]" if sync_flag == "1" else "[ ]"
        stdscr.addstr(f"{sort_number}. {is_synced} {wrapped_url}\n", highlight)

    stdscr.refresh()

def show_popup(stdscr, detail_text):
    """Display a popup with detailed information."""
    max_y, max_x = stdscr.getmaxyx()
    popup_width = max_x - 4
    popup_height = max_y - 4

    detail_lines = textwrap.wrap(detail_text, popup_width - 2)
    popup_win = curses.newwin(popup_height, popup_width, 2, 2)
    popup_win.border()

    for i, line in enumerate(detail_lines):
        if i >= popup_height - 2:
            break
        popup_win.addstr(i + 1, 1, line)

    popup_win.addstr(popup_height - 2, 1, "Press 'i' or ESC to close.")
    popup_win.refresh()

    while True:
        key = stdscr.getch()
        if key in (ord('i'), 27):  # Close on 'i' or ESC
            break

def main(stdscr, simple_mode=False):
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
            current_index = 0  # Reset index to top when moving to the next page

        elif key == curses.KEY_UP and current_index > 0:
            current_index -= 1
        elif key == curses.KEY_UP and current_index == 0 and current_page > 0:
            current_page -= 1
            current_index = ITEMS_PER_PAGE - 1  # Set index to the last item of the previous page

        elif key == curses.KEY_RIGHT and (current_page + 1) * ITEMS_PER_PAGE < len(sources):
            current_page += 1
            current_index = 0
        elif key == curses.KEY_LEFT and current_page > 0:
            current_page -= 1
            current_index = 0

        elif key == ord('q'):
            break

        elif key == ord('i'):
            url, sync_flag = sources[current_page * ITEMS_PER_PAGE + current_index].split(",")
            utility = Utility()
            try:
                manga = utility.get_manga(url)
                detail_text = f"Title: {manga.title}\n\nDescription:\n{manga.desc.strip()}" if manga.desc.strip() else "[No description available]"
            except Exception as e:
                detail_text = f"Error fetching details: {str(e)}"

            show_popup(stdscr, detail_text)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sort and display manga URLs with optional details.")
    parser.add_argument("-s", "--simple", action="store_true", help="Display only URLs without details")

    args = parser.parse_args()

    if args.simple:
        print("Simple mode enabled")
        ITEMS_PER_PAGE = 4

    if ITEMS_PER_PAGE > os.get_terminal_size().lines - 10:
        ITEMS_PER_PAGE = os.get_terminal_size().lines - 10

    if not os.path.exists("config"):
        os.makedirs("config")

    curses.wrapper(main, simple_mode=not args.simple)
