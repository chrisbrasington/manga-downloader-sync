#!/usr/bin/env python3
from parser import Utility 
import glob, os, shutil, sys
from tqdm import tqdm
import subprocess

# change sync destination 
device = '/run/media/chris/KOBOeReader'
sync_destination = f'{device}/manga'
if len(sys.argv) > 1:
    sync_destination = sys.argv[1]

# Open the text file and read the lines into a list
with open("sources.txt") as f:
    sources = f.readlines()

# Strip the leading and trailing whitespace from each line
sources = [source.strip() for source in sources]

# parsing utility
util = Utility()

# check device existence 
if not os.access(sync_destination, os.W_OK):
    print('kobo not plugged in, skipping sync')
else:
    print('✓ kobo detected')

# Iterate over the list of sources
for source in sources:

    # url and secondary optional "combine" flag
    parts = source.split(",")
    if len(parts) == 2:
        source, combine = parts
    else:
        source, combine = parts[0], False

    # parse feed if known source
    known, tmp_dir, title = util.parse_feed(source, combine)

    # sync to device
    if(known):

        # chapter destination
        sync_dest = os.path.join(sync_destination, title)

        # if device exists
        if os.access(sync_destination, os.W_OK):
            
            if not os.path.exists(sync_dest):
                os.makedirs(sync_dest)

            # if combined, only move single file
            if combine:
                if os.access(sync_destination, os.W_OK):
                    source_path = glob.glob(f'{tmp_dir}/*combo.pdf')[0]
                    file_name = os.path.basename(source_path)

                    sync_dest_file = os.path.join(sync_dest, file_name)
                    if not os.path.exists(sync_dest_file):
                        for prior_combo in glob.glob(f'{sync_dest}/*combo.pdf'):
                            os.remove(prior_combo)

                        sync_dir = os.path.dirname(sync_dest_file)
                        if not os.path.exists(sync_dir):
                            os.makedirs(sync_dir)

                        print(f'copying {file_name}, please wait.., do not unplug!')
                        pbar = tqdm(total=1)
                        shutil.copy(source_path, sync_dest_file)
                        pbar.update(1)
                        pbar.close()
                        util.synced.append(file_name)
                    else:
                        # fake 100% 1/1 bar for consistent look
                        pbar = tqdm(total=1)
                        pbar.update(1)
                        pbar.close()

                    print(f'  ✓ synced: {file_name} (combined)')

            force_sync = False
            if len(os.listdir(sync_dest)) == 1 and not any(file.endswith('combo.pdf') for file in os.listdir(sync_dest)):
                force_sync = True

            # if more than combo file exists in destination, update individual chapters too
            if len(os.listdir(sync_dest)) == 0 or len(os.listdir(sync_dest)) > 1 or force_sync:

                # find latest chapter on device
                latest_chapter_num = -1
                try:
                    latest_chapter = sorted(os.listdir(sync_dest), key=util.extract_number)[-1]     
                    latest_chapter_num = util.extract_number(latest_chapter)
                except:
                    # no chapters exists, that's fine
                    print('  No chapters on device')

                # print latest on device
                if latest_chapter_num != 0:
                    print(f'  ✓ device: {latest_chapter_num}')          

                # check every file on device against cache, pdf only
                for filename in tqdm(sorted(glob.glob(tmp_dir + '/*.pdf'), key=util.extract_number)):

                    if 'pdf' in filename:

                        # get chapter number from file
                        current_chapter_num = util.extract_number(filename)

                        # if cached chapter is newer than device chapter, sync to device
                        if latest_chapter_num < current_chapter_num:

                            sync_dest_file = os.path.join(sync_dest, os.path.basename(filename))
                            util.synced.append(os.path.basename(filename))

                            if os.access(sync_destination, os.W_OK):
                                if not os.path.exists(sync_dest_file):
                                    os.makedirs(os.path.dirname(sync_dest_file), exist_ok=True)
                                    shutil.copy(filename, sync_dest_file)
                                # print(f'    ✓ {filename}')
                    pass

    break

# print summary of download and sync
util.print_summary()