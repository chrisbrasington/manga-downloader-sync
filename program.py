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
    print('kobo not plugged in')
else:
    print('✓ kobo detected')

# Iterate over the list of sources
for source in sources:

    known, tmp_dir, title = util.parse_feed(source)

    if(known):

        sync_dest = os.path.join(sync_destination, title)

        print('Syncing:', tmp_dir, '<-->', sync_dest)

        for filename in os.listdir(tmp_dir):
            
            filepath = os.path.join(tmp_dir, filename)
            sync_dest_file = os.path.join(sync_dest, filename)

            if os.access(sync_destination, os.W_OK):
                if not os.path.exists(sync_dest_file):
                    os.makedirs(os.path.dirname(sync_dest_file), exist_ok=True)
                    shutil.copy(filepath, sync_dest_file)
                print(f'✓ {filename}')

    break