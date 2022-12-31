import feedparser, os, requests, shutil, urllib
from tqdm import tqdm
import MangaDexPy

class Utility:
    def extract(self, url):
        if('danke' in url):
            url, name = self.extract_danke_moe(url)
            return True, url, name
        else:
            print('unsupported feed')
            return False, None, dl

    def extract_danke_moe(self, url):
        dl = url.split("read/manga/")[-1].strip('/')
        dl = dl.rsplit("/", 1)[0]
        base = 'https://danke.moe/api/download_chapter/'
        return f'{base}{dl}', f'{dl.replace("/","-")}.cbz'

    def parse_feed(self, source):
        if('danke.moe' in source and 'rss' not in source):
            print('supported - danke.moe')
            source = source.replace('https://danke.moe/read/manga/','https://danke.moe/read/other/rss/').strip('/')

        if('mangadex' in source):
            print('supported - mangadex')
            self.parse_mangadex(source)

        if('rss' in source):
            result, name = self.parse_rss_feed(source)
            return True, result, name
        else: 
            print(f'unsupported feed: {source}')
            return False, None, None
        
    def parse_rss_feed(self, source):
        # Parse the RSS feed
        feed = feedparser.parse(source)

        # Print the feed information
        print(f'{feed.feed.title} - {feed.feed.link}')

        tmp_dir = f'tmp/{feed.feed.title}'

        # Print each entry in the feed
        for entry in feed.entries:
            print(entry.title) #entry.link

            result = self.extract(entry.link)
            is_known, dl, name = result
            
            if(is_known):
                
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
        return tmp_dir, feed.feed.title

    def parse_mangadex(self, source):
        print(source)
        cli = MangaDexPy.MangaDex()
        
        with open("mangadex.secret") as f:
            lines = f.readlines()
            lines = [source.strip() for source in sources]
            print(lines)