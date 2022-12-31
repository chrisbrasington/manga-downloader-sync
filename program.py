from parser import Utility 
import feedparser, os, requests, urllib
from tqdm import tqdm

# Open the text file and read the lines into a list
with open("sources.txt") as f:
    sources = f.readlines()

# Strip the leading and trailing whitespace from each line
sources = [source.strip() for source in sources]

util = Utility()

# Iterate over the list of sources
for source in sources:
    # Parse the RSS feed
    feed = feedparser.parse(source)

    # Print the feed information
    print(feed.feed.title, feed.feed.link, end='\n\n')

    # Print each entry in the feed
    for entry in feed.entries:
        print(entry.title, entry.link)

        result = util.extract(entry.link)
        is_known, dl, name = result
        
        if(is_known):
            tmp_dir = f'tmp/{feed.feed.title}'
            
            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)            

            filename = os.path.basename(name)
            filepath = os.path.join(tmp_dir, filename)

            if not os.path.exists(filepath):

                # Send an HTTP request to get the file size (if available) and the file content
                response = requests.get(dl, headers={"Range": "bytes=0-"})
                file_size = int(response.headers.get("Content-Length", 0))

                # Download the file and show a progress bar
                with tqdm(total=file_size, unit="B", unit_scale=True, miniters=1, desc=filename) as t:
                    with open(filepath, "wb") as f:
                        for chunk in response.iter_content(chunk_size=1024):
                            # Write the chunk to the file
                            f.write(chunk)
                            # Update the progress bar manually
                            t.update(len(chunk))
            else: 
                print('✓ ', name)
