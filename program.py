#!/usr/bin/env python3
from classes.parser import Utility 
import glob, os, shutil, sys
from tqdm import tqdm
import subprocess
import builtins, textwrap

# def print_tabbed(text):

#     wrapped_text = textwrap.fill(text, width=80)
#     builtins.print(wrapped_text.replace("\n", "\n    "))

# print = print_tabbed

# change sync destination 
device = '/run/media/chris/KOBOeReader'
sync_destination = f'{device}/manga'
if len(sys.argv) > 1:
    sync_destination = sys.argv[1]

sources = []
haitus = []
completed = []

# Open the text file and read the lines into a list
if os.path.exists('sources.txt'):
    with open("sources.txt") as f:
        sources = f.readlines()

    # Strip the leading and trailing whitespace from each line
    sources = [source.strip() for source in sources]

if os.path.exists('haitus.txt'):
    with open("haitus.txt") as f:
        haitus = f.readlines()

    # Strip the leading and trailing whitespace from each line
    haitus = [h.strip() for h in haitus]

if os.path.exists('completed.txt'):
    with open("completed.txt") as f:
        completed = f.readlines()

    # Strip the leading and trailing whitespace from each line
    completed = [h.strip() for h in completed]

if len(sources) == 0 and len(haitus) == 0 and len(completed) == 0:
    print('no sources, aborting')
    sys.exit()

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
        util.sync(tmp_dir, sync_destination, title, combine)

# Iterate over the list of sources
for source in completed:

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
        util.sync(tmp_dir, sync_destination, title, combine)
    
# Iterate over the list of sources in hiatus
for source in haitus:

    # url and secondary optional "combine" flag
    parts = source.split(",")
    if len(parts) == 2:
        source, combine = parts
    else:
        source, combine = parts[0], False

    # parse feed if known source
    known, tmp_dir, title = util.parse_feed(source, combine)

    # do not sync to these to device
    print('  haitus, skipping sync', end='')

# print summary of download and sync
util.print_summary()