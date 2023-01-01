#!/usr/bin/env python3
from parser import Utility 
import os, shutil

sync_destination = '/run/media/chris/KOBOeReader/manga'

# Open the text file and read the lines into a list
with open("sources.txt") as f:
    sources = f.readlines()

# Strip the leading and trailing whitespace from each line
sources = [source.strip() for source in sources]

util = Utility()

if not os.access(sync_destination, os.W_OK):
    print('kobo not plugged in, skipping sync')
else:
    print('✓ kobo detected')

# Iterate over the list of sources
for source in sources:

    parts = source.split(",")

    if len(parts) == 2:
        source, combine = parts
    else:
        source, combine = parts[0], False

    known, tmp_dir, title = util.parse_feed(source, combine)

    if(known):

        sync_dest = os.path.join(sync_destination, title)

        if os.access(sync_destination, os.W_OK):
            # print('  Syncing:', tmp_dir, '<-->', sync_dest)
            print('  Syncing to device...')

            if combine:
                if os.access(sync_destination, os.W_OK):
                    filename = f'{title}.pdf'
                    filepath = os.path.join(tmp_dir, filename)
                    sync_dest_file = os.path.join(sync_dest, filename)

                    if not os.path.exists(sync_dest_file):
                        os.makedirs(os.path.dirname(sync_dest_file), exist_ok=True)
                        shutil.copy(filepath, sync_dest_file)
                    print(f'    ✓ {filename} (combined)')

            else:
                latest_chapter_num = 0
                try:
                    latest_chapter = sorted(os.listdir(sync_dest), key=util.extract_number)[-1]     
                    latest_chapter_num = util.extract_number(latest_chapter)
                except:
                    print('  No chapters on device')

                if latest_chapter_num != 0:
                    print(f'  Latest chapter on device: {latest_chapter_num}')          

                for filename in sorted(os.listdir(tmp_dir), key=util.extract_number):

                    if 'pdf' in filename:
                        current_chapter_num = util.extract_number(filename)

                        if latest_chapter_num < current_chapter_num:

                            filepath = os.path.join(tmp_dir, filename)
                            sync_dest_file = os.path.join(sync_dest, filename)

                            if os.access(sync_destination, os.W_OK):
                                if not os.path.exists(sync_dest_file):
                                    os.makedirs(os.path.dirname(sync_dest_file), exist_ok=True)
                                    shutil.copy(filepath, sync_dest_file)
                                print(f'    ✓ {filename}')