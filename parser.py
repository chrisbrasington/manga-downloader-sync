import feedparser, os, re, requests, shutil, urllib
from tqdm import tqdm
import MangaDexPy
from MangaDexPy import downloader
import contextlib, io, zipfile

class Utility:

    def __init__(self):
        self.cli = MangaDexPy.MangaDex()
        with open("mangadex.secret") as f:
            secrets = f.readlines()
            secrets = [line.strip() for line in secrets]
        self.cli.login(secrets[0], secrets[1])

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
            source = source.replace('https://danke.moe/read/manga/','https://danke.moe/read/other/rss/').strip('/')

        if('mangadex' in source):
            result, name = self.parse_mangadex(source)
            return True, result, name

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
        if('danke.moe' in feed.feed.link):
            print(f'{feed.feed.title} - danke.moe')
        else:    
            print(f'{feed.feed.title} - {feed.feed.link}')

        tmp_dir = f'tmp/{feed.feed.title}'

        # Print each entry in the feed
        for entry in feed.entries:
            print(' ', entry.title) #entry.link

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
                
                print('  ✓', name)

        return tmp_dir, feed.feed.title

    def parse_mangadex(self, source):
        pattern = r"/mangadex/(?P<guid>[\w-]+)/"
        match = re.search(pattern, source)
        guid = match.group("guid")

        manga = self.cli.get_manga(guid)
        print(manga.title['en'], '- mangadex')
        tmp_dir = f"tmp/{manga.title['en']}"

        chapters = reversed(manga.get_chapters())
        for chapter in chapters:
            if(chapter.language == 'en'):

                tmp_chapter = f"{tmp_dir}/{manga.title['en']} - {chapter.volume}"
                print(manga.title['en'], '- Chapter', chapter.volume)
                zip_name = f"{tmp_chapter}.cbz"

                if not os.path.exists(zip_name):

                    if not os.path.exists(tmp_chapter):
                        os.makedirs(tmp_chapter)       

                    with contextlib.redirect_stdout(io.StringIO()):
                        downloader.dl_chapter(chapter, tmp_chapter)

                    # Create a new ZIP file
                    cbz_file = zipfile.ZipFile(f"{tmp_chapter}.cbz", "w")

                    # Walk through the files and directories in the comic directory
                    for root, dirs, files in os.walk(tmp_chapter):
                        # Add the files to the ZIP file
                        for file in files:
                            cbz_file.write(os.path.join(root, file))

                    # Close the ZIP file
                    cbz_file.close()

                    shutil.rmtree(tmp_chapter)

                print('  ✓', manga.title['en'], chapter.volume)

        return tmp_dir, manga.title['en']