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
    
    # Increase the popup size to 75% of the screen
    popup_height = (max_y * 3) // 4
    popup_width = (max_x * 3) // 4
    popup_start_y = (max_y - popup_height) // 2
    popup_start_x = (max_x - popup_width) // 2

    popup_win = curses.newwin(popup_height, popup_width, popup_start_y, popup_start_x)
    popup_win.border()

    # Split the text into paragraphs first (based on \n\n)
    paragraphs = detail_text.split('\n\n')
    
    # Wrap each paragraph separately and ensure extra spacing
    wrapped_paragraphs = []
    for paragraph in paragraphs:
        wrapped_paragraph = textwrap.fill(paragraph, width=popup_width - 4)
        wrapped_paragraphs.append(wrapped_paragraph.split('\n'))

    # Add the title at the top of the popup
    popup_win.addstr(1, 2, title[:popup_width - 4])  # Truncate the title if needed

    # Track the current line index in the window
    current_line = 2  # Start just below the title

    # Add each wrapped paragraph with extra space between paragraphs
    for paragraph in wrapped_paragraphs:
        for line in paragraph:
            if current_line < popup_height - 2:
                popup_win.addstr(current_line, 2, line[:popup_width - 4])
                current_line += 1
        # Add extra space after each paragraph
        if current_line < popup_height - 2:
            current_line += 1  # This will give some space between paragraphs

    popup_win.refresh()

    while True:
        key = popup_win.getch()
        if key in (ord('i'), ord('q'), 27):  # Close on 'i' or ESC
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

        # spacebar will toggle the sync flag and save file
        elif key == ord(' '):
            url, sync_flag = sources[current_page * ITEMS_PER_PAGE + current_index].split(",")
            sync_flag = "1" if sync_flag == "0" else "0"
            sources[current_page * ITEMS_PER_PAGE + current_index] = f"{url},{sync_flag}"
            write_file(SOURCES_FILE, sources)

        elif key == ord('i'):
            url, sync_flag = sources[current_page * ITEMS_PER_PAGE + current_index].split(",")
            utility = Utility()
            try:
                manga = utility.get_manga(url)
                description = f"{manga.desc.strip()}"

                # remove [*](*) hyperlinks from description using regex inline not utility
                description = re.sub(r'\[.*?\]\(.*?\)', '', description)
                description = description.replace('\n\n', '\n')
                description = description.replace('___', '')

                # trim space and newline from end of description
                description = description.strip()

                # add status
                detail_text = f"~~~~~~~~~~\n\nStatus: {manga.status}"

                genres = [tag['attributes']['name']['en'] for tag in manga.data['attributes']['tags'] if tag['attributes']['group'] == 'genre']

                themes = [tag['attributes']['name']['en'] for tag in manga.data['attributes']['tags'] if tag['attributes']['group'] == 'theme']

                demographic = manga.data['attributes']['publicationDemographic']

                # add genres
                detail_text += f"\n\nGenres: {', '.join(genres)}"

                # add themes
                detail_text += f"\n\nThemes: {', '.join(themes)}"

                # add demographic
                detail_text += f"\n\nDemographic: {demographic}"

                # add description
                detail_text += f"\n\nDescription: {description}"

                # add url
                detail_text += f"\n\nURL: {url}"

                # determine if synced to ereader if sync_flag contains 1
                synced = "Yes" if sync_flag == " 1" else "No"

                # add synced status
                detail_text += f"\n\nSync Status: {synced}"

                # detail files on disk, look in tmp/ for the japanese title as the folder
                folder_path = os.path.join('tmp', manga.get_japanese_title())

                # Check if the folder exists
                if not os.path.exists(folder_path):
                    print(f"Folder '{folder_path}' does not exist.")
                    detail_text += "\n\nNo files found."
                else:
                    # Add all files from the folder
                    files = os.listdir(folder_path)
                    for file in files:
                        detail_text += f"\n{file}"

                show_popup(stdscr, manga.get_combined_title(), detail_text)
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
