#!/usr/bin/env python3
import curses
import os
import sys
import argparse
import textwrap
from classes.parser import Utility  # Assuming Utility is imported from parser


# Configuration for easy modification
ITEMS_PER_PAGE = 5
SYNC_FILE = "config/sync.txt"
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

def reorder_sync():
    """Reorders sync.txt to match sources.txt by removing and then re-adding entries that are common."""
    # Read the files
    sources = read_file(SOURCES_FILE)
    sync = read_file(SYNC_FILE)

    # get all entires from sources.txt
    ordered_sync = [url for url in sources]

    # append any URLs in sync but not in sources to the end
    unordered_sync = [url for url in sync if url not in ordered_sync]

    # combine the ordered and unordered sync URLs
    final_sync = ordered_sync + unordered_sync

    # write the final list to sync.txt
    write_file(SYNC_FILE, final_sync)

def sort_files():
    """Sorts sources.txt first, then sync.txt based on sources.txt."""
    # Read the files
    sources = read_file(SOURCES_FILE)
    sync = read_file(SYNC_FILE)

    # Sort sync.txt based on the order in sources.txt
    ordered_sync = [url for url in sources if url in sync]

    # Append any URLs in sync but not in sources to the end
    unordered_sync = [url for url in sync if url not in sources]

    # Combine the ordered and unordered sync URLs
    final_sync = ordered_sync + unordered_sync
    write_file(SYNC_FILE, final_sync)

    return sources, final_sync

def display_menu(stdscr, sync, current_page, current_index, show_details=True):
    """Displays the menu with the sync list, including sort numbers and pagination."""
    max_y, max_x = stdscr.getmaxyx()
    visible_lines = max_y - 6  # Number of lines we can display, leaving room for other UI elements

    start_index = current_page * ITEMS_PER_PAGE
    end_index = min((current_page + 1) * ITEMS_PER_PAGE, len(sync))

    # Display the page information
    total_pages = (len(sync) // ITEMS_PER_PAGE) + (1 if len(sync) % ITEMS_PER_PAGE > 0 else 0)
    stdscr.clear()
    stdscr.addstr(f"Page [{current_page + 1} of {total_pages}]\n\n")
    stdscr.addstr("Use arrow keys to navigate, type a number to change the sort order, and press Enter to confirm.\n")
    stdscr.addstr("Press Q to quit.\n\n")

    # Display the entries with sort numbers
    for idx in range(start_index, end_index):
        url = sync[idx]
        highlight = curses.A_REVERSE if idx == start_index + current_index else curses.A_NORMAL
        sort_number = idx + 1  # Sort number is 1-based

        # Wrap the URL to avoid exceeding terminal width
        wrapped_url = textwrap.fill(url, width=max_x - 5)  # Adjust the width for margin

        # Display the URL with the sort number
        stdscr.addstr(f"{sort_number}. {wrapped_url}\n", highlight)

        if show_details:
            # Create an instance of Utility class to fetch manga details
            utility = Utility()
            try:
                manga = utility.get_manga(url)
                stdscr.addstr(f"   Title: {manga.title}\n")
                
                # Only display description if it's not empty
                if manga.desc.strip():
                    stdscr.addstr("   Description: \n")
                    # Wrap the description to fit within the terminal width
                    wrapped_desc = textwrap.fill(manga.desc.strip(), width=max_x - 5)
                    # Indent each wrapped line
                    for line in wrapped_desc.split("\n"):
                        stdscr.addstr(f"     {line}\n")
                else:
                    stdscr.addstr("   Description: [No description available]\n")
            except Exception as e:
                stdscr.addstr(f"   Error fetching details: {str(e)}\n")

    stdscr.refresh()


def main(stdscr, simple_mode=False):
    curses.curs_set(0)

    # Re-order sync.txt at the start to match sources.txt order
    reorder_sync()

    # Re-sort both sources.txt and sync.txt
    sources, sync = sort_files()
    current_page = 0
    current_index = 0
    max_y, max_x = stdscr.getmaxyx()

    while True:
        display_menu(stdscr, sync, current_page, current_index, show_details=not simple_mode)

        key = stdscr.getch()

        if key == curses.KEY_DOWN and current_index < ITEMS_PER_PAGE - 1:
            current_index += 1
        elif key == curses.KEY_DOWN and current_index == ITEMS_PER_PAGE - 1:
            if (current_page + 1) * ITEMS_PER_PAGE < len(sync):
                current_page += 1
            current_index = 0  # Reset index to top when moving to the next page

        elif key == curses.KEY_UP and current_index > 0:
            current_index -= 1
        elif key == curses.KEY_UP and current_index == 0 and current_page > 0:
            current_page -= 1
            current_index = ITEMS_PER_PAGE - 1  # Set index to the last item of the previous page

        try:
            if key == ord('q'):
                break
            elif key == ord('\n'):  # Enter key to change sort number
                stdscr.addstr(max_y - 3, 0, "Enter new sort number: ")
                curses.echo()
                new_sort_number = int(stdscr.getstr().decode("utf-8").strip())
                curses.noecho()

                # Adjust the sorting based on the new sort number
                if 1 <= new_sort_number <= len(sync):
                    new_sort_number -= 1  # Convert to 0-based index
                    url = sync[current_page * ITEMS_PER_PAGE + current_index]
                    sync.remove(url)
                    sync.insert(new_sort_number, url)

                    # Re-write the updated sync.txt and sources.txt
                    write_file(SYNC_FILE, sync)
                    write_file(SOURCES_FILE, sync)  # Save to sources.txt as well

                    current_page = 0
                    current_index = 0

        except ValueError:
            pass  # Ignore invalid sort number inputs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sort and display manga URLs with optional details.")
    parser.add_argument("-s", "--simple", action="store_true", help="Display only URLs without details")

    args = parser.parse_args()

    print(args)

    # if simple is present 
    if args.simple:
        print("Simple mode enabled")
        # change ITEMS_PER_PAGE globally
        ITEMS_PER_PAGE = 70

        # make sure not over length of window by checking height of window
        if ITEMS_PER_PAGE > os.get_terminal_size().lines - 7:
            ITEMS_PER_PAGE = os.get_terminal_size().lines - 7
        

    if not os.path.exists("config"):
        os.makedirs("config")
    
    curses.wrapper(main, simple_mode=args.simple)
