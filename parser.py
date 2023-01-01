import feedparser, os, re, requests, shutil, urllib
from tqdm import tqdm
import MangaDexPy
from MangaDexPy import downloader
import contextlib, io, zipfile
from PIL import Image

class Utility:

    # Private constructor
    def __init__(self):
        self.cli = MangaDexPy.MangaDex()

    # Static instance method
    @staticmethod
    def instance():
        if not hasattr(Utility, "_instance"):
            Utility._instance = Utility()
        return Utility._instance

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

    def parse_feed(self, source, combine):
        if('danke.moe' in source and 'rss' not in source):
            source = source.replace('https://danke.moe/read/manga/','https://danke.moe/read/other/rss/').strip('/')

        success = False
        result = None
        name = None
        did_work = False

        if('mangadex' in source):
            result, name, did_work = self.parse_mangadex(source)
            success = True
        elif('rss' in source):
            result, name, did_work = self.parse_rss_feed(source)
            success = True
        else: 
            print(f'unsupported feed: {source}')
            success = False

        if(combine) and did_work:
            self.combine(result)
        
        # conver from cbz to pdf
        self.convert_to_pdf(result, combine)
        
        return success, result, name
    
    def extract_number(self, s):
        match = re.search(r'\d+(\.\d+)?', s)
        value = match.group()
        return int(value)


    def convert_to_pdf(self,dir, combine):

        print('converting...')

        combo_file = f'{dir}.cbz'

        print(combo_file)
        
        for root, dirs, files in os.walk(dir):
            # Add the files to the ZIP file
            for file in files:

                # skip over existing pdfs
                if 'pdf' not in file:

                    if combine and file not in combo_file:
                        # print(f'ignoring {file}')
                        continue
                    else:
                        print('  combo file match!')
            
                    file_path = os.path.join(dir, file)
                    pdf_path = file_path.replace('cbz','pdf')

                    if not os.path.exists(pdf_path):
                        print(f'  converting to pdf...')

                        with zipfile.ZipFile(file_path, 'r') as cbz_file:    
                            cbz_file.extractall('convert')
                        
                        num_pages = len(os.listdir('convert'))

                        images = []

                        directories = [d for d in os.listdir('convert') if os.path.isdir(os.path.join('convert', d))]
                        directories = sorted(directories, key=self.extract_number)

                        if len(directories) > 0:
                            for image in directories:
                                if(os.path.isdir(os.path.join('convert', image))):
                                    sub_dir = os.path.join('convert', image)
                                    for image in os.listdir(sub_dir):
                                        images.append(Image.open(os.path.join(sub_dir, image)))                                
                        else:
                            for image in os.listdir('convert'):
                                images.append(Image.open(os.path.join('convert', image)))

                        converted_images = []

                        # Iterate through the list of images and convert each one to grayscale
                        for image in images:
                            converted_images.append(image.convert("L"))

                        # Save the images as a PDF
                        converted_images[0].save(pdf_path, "PDF" ,resolution=100.0, save_all=True, append_images=converted_images[1:])

                        shutil.rmtree('convert')

                    else:
                        print(f'  ✓ {pdf_path} exists')

    def combine(self, dir):
        file_name = dir.replace("tmp/","")
        if(os.path.exists(f'tmp/{file_name}/{file_name}.cbz')):
            os.remove(f'tmp/{file_name}/{file_name}.cbz')

        for root, dirs, files in os.walk(dir):
            # Add the files to the ZIP file
            for file in files:
                if(file.endswith('cbz') or file.endswith('zip')):
                    file = os.path.join(root, file)
                    dest = file.rsplit('.',1)[0]
                    with zipfile.ZipFile(file, "r") as zip_ref:
                        zip_ref.extractall(dest)
                    os.remove(file) 
        
        folders = []
        for root, dirs, _ in os.walk(dir):
            # folders.extend(dirs)
            for folder in dirs:
                folder = os.path.join(dir, folder)
                folders.append(folder)

        print('combining:', len(folders))
        
        shutil.make_archive('combo', 'zip', dir)
        shutil.move(f'combo.zip', f'tmp/{file_name}/{file_name}.cbz')

        # re-archive
        for root, dirs, files in os.walk(f'tmp/{file_name}'):
            for chapter in dirs:
                chapter = f'{dir}/{chapter}'
                print(chapter)
                self.create_cbz(chapter)

    def parse_rss_feed(self, source):
        # Parse the RSS feed
        feed = feedparser.parse(source)

        did_work = False

        # Print the feed information
        if('danke.moe' in feed.feed.link):
            print(f'{feed.feed.title} - danke.moe')
        else:    
            print(f'{feed.feed.title} - {feed.feed.link}')

        tmp_dir = f'tmp/{feed.feed.title}'

        # Print each entry in the feed
        for entry in feed.entries:
            # print(' ', entry.title) #entry.link

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
                    did_work = True
                    print('  ✓', name)

        if not did_work:
            match = re.search(r'\d+', feed.entries[0].title)
            if match:
                number = match.group()
                print(f'  ✓ up-to-date: Chapter:', number)
            else:
                print(f'  ✓ up-to-date: Chapter:', feed.entries[0].title)

        return tmp_dir, feed.feed.title, did_work

    def parse_mangadex(self, source):
        did_work = False
        guid = None

        pattern = r"/mangadex/(?P<guid>[\w-]+)/"
        match = re.search(pattern, source)

        if match:
            guid = match.group("guid")
        else:
            pattern = r"/title/(?P<guid>[\w-]+)/"
            match = re.search(pattern, source)
            if match:
                guid = match.group("guid")
            else:
                print('failure parsing mangadex guid')
                return



        # Get the single instance of the Utility class
        utility = Utility.instance()

        # Use the cli attribute of the Utility instance
        manga = utility.cli.get_manga(guid)
        
        print(manga.title['en'], '- mangadex')
        tmp_dir = f"tmp/{manga.title['en']}"

        latest_chapter = None

        chapters = reversed(manga.get_chapters())
        for chapter in chapters:
            if(chapter.language == 'en'):

                if latest_chapter is None:
                    latest_chapter = chapter

                tmp_chapter = f"{tmp_dir}/{manga.title['en']} - {chapter.chapter}" # chapter number not volume
                # print(manga.title['en'], '- Chapter', chapter.volume)
                zip_name = f"{tmp_chapter}.cbz"

                if not os.path.exists(zip_name):

                    if not os.path.exists(tmp_chapter):
                        os.makedirs(tmp_chapter)       

                    with contextlib.redirect_stdout(io.StringIO()):
                        downloader.dl_chapter(chapter, tmp_chapter)

                    self.create_cbz(tmp_chapter)
                    did_work = True
                    print('  ✓', manga.title['en'], chapter.chapter)

        if not did_work:
            print('  ✓ up-to-date: Chapter:', latest_chapter.chapter)

        return tmp_dir, manga.title['en'], did_work

    def create_cbz(self, tmp_chapter):
        shutil.make_archive(tmp_chapter, 'zip', tmp_chapter)
        shutil.move(f'{tmp_chapter}.zip', f'{tmp_chapter}.cbz')
        shutil.rmtree(tmp_chapter)