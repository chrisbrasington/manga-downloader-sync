import MangaDexPy
from MangaDexPy import downloader
import feedparser, os, re, requests, shutil, urllib
from tqdm import tqdm
import contextlib, glob, io, sys, textwrap, traceback, zipfile
from PIL import Image
from pdfrw import PdfReader, PdfWriter   

# utility parser class
class Utility:

    # Private constructor
    def __init__(self):
        self.cli = MangaDexPy.MangaDex()
        self.summary = []
        self.synced = []

    # Static instance method
    @staticmethod
    def instance():
        if not hasattr(Utility, "_instance"):
            Utility._instance = Utility()
        return Utility._instance

    # combine all files into single pdf (if requested)
    def combine(self, dir, author):

        file_name = dir.replace("tmp/","")
        if(os.path.exists(f'tmp/{file_name}/{file_name}.cbz')):
            os.remove(f'tmp/{file_name}/{file_name}.cbz')

        # work in manga/tmp folder
        working_dir = f'tmp/{file_name}/tmp'
        os.makedirs(working_dir)      

        for root, dirs, files in os.walk(dir):
            # Add the files to the ZIP file
            for file in sorted(files, key=self.extract_number):
                if(file.endswith('cbz') or file.endswith('zip')):
                    file = os.path.join(root, file)
                    # dest = file.rsplit('.',1)[0]
                    dest = f"{working_dir}/{file.rsplit('.',1)[0].split('/')[-1]}"
                    with zipfile.ZipFile(file, "r") as zip_ref:
                        zip_ref.extractall(dest)
    
        images = []

        chapter_lowest = None
        chapter_highest = None

        # for each chapter (sorted) and images (sorted)
        for chapter in sorted(os.listdir(working_dir), key=self.extract_number):

            if chapter_lowest is None:
                chapter_lowest = self.extract_number(chapter)

            print('\n', chapter)
            for image in sorted(os.listdir(os.path.join(working_dir, chapter)), key=self.extract_number):
                chapter_highest = self.extract_number(chapter)
                print(' ', image.split('.')[0], end=' ')
                image_path = os.path.join(working_dir, chapter, image)
                # grayscale convert
                converted_image = Image.open(image_path).convert("L")
                images.append(converted_image)
        
        pdf_path = f'tmp/{file_name}/{file_name}-{chapter_lowest}-{chapter_highest}-combo.pdf'

        # Save the images as a PDF
        images[0].save(pdf_path, "PDF" ,resolution=100.0, save_all=True, append_images=images[1:])

        # set author metadata of pdf
        trailer = PdfReader(pdf_path)    
        trailer.Info.Author = author
        PdfWriter(pdf_path, trailer=trailer).write()

        # remove temp dir
        shutil.rmtree(working_dir)

        print(f'\n  ✓ {file_name}.pdf')

    # convert individual file from cbz to pdf
    def convert_to_pdf(self, dir, author):

        # if combo requested, use {title}.cbz
        combo_file = f'{dir}.cbz'
        
        for root, dirs, files in os.walk(dir):
            # Add the files to the ZIP file
            for file in sorted(files, key=self.extract_number):
                # skip over existing pdfs
                if 'pdf' not in file:
            
                    # get cbz and pdf name
                    file_path = os.path.join(dir, file)
                    pdf_path = file_path.replace('cbz','pdf')

                    # if pdf not existing, convert
                    if not os.path.exists(pdf_path):
                        print(f'  converting to pdf... {pdf_path}')

                        # extract cbz/zip
                        with zipfile.ZipFile(file_path, 'r') as cbz_file:    
                            cbz_file.extractall('convert')
                        
                        num_pages = len(os.listdir('convert'))

                        images = []
                        directories = [d for d in os.listdir('convert') if os.path.isdir(os.path.join('convert', d))]
                        directories = sorted(directories, key=self.extract_number)

                        # some chapters include subdirectories, allow a depth of 1
                        if len(directories) > 0:
                            for image in directories:
                                if(os.path.isdir(os.path.join('convert', image))):
                                    sub_dir = os.path.join('convert', image)
                                    for image in os.listdir(sub_dir):
                                        images.append(Image.open(os.path.join(sub_dir, image)))                               
                        # most chapters have images at root
                        else:
                            images_dr = os.listdir('convert')
                            images_dr = sorted(images_dr, key=self.extract_number)

                            for image in images_dr:
                                images.append(Image.open(os.path.join('convert', image)))

                        converted_images = []

                        # Iterate through the list of images and convert each one to grayscale
                        for image in images:
                            converted_images.append(image.convert("L"))

                        # Save the images as a PDF
                        converted_images[0].save(pdf_path, "PDF" ,resolution=100.0, save_all=True, append_images=converted_images[1:])

                        # remove temp image extraction folder
                        shutil.rmtree('convert')

                        # set author metadata of pdf
                        trailer = PdfReader(pdf_path)    
                        trailer.Info.Author = author
                        PdfWriter(pdf_path, trailer=trailer).write()

    # create cbz - rename zip to cbz
    def create_cbz(self, tmp_chapter):
        shutil.make_archive(tmp_chapter, 'zip', tmp_chapter)
        shutil.move(f'{tmp_chapter}.zip', f'{tmp_chapter}.cbz')
        shutil.rmtree(tmp_chapter)

    # extract rss name from danke feed
    def extract_danke_moe(self, url):
        dl = url.split("read/manga/")[-1].strip('/')
        dl = dl.rsplit("/", 1)[0]
        base = 'https://danke.moe/api/download_chapter/'
        return f'{base}{dl}', f'{dl.replace("/","-")}.cbz'

    # extract number from chapter metadata or filename
    def extract_number(self, s):
        
        try:
            if type(s) == MangaDexPy.chapter.Chapter:
                return float(s.chapter)

            match = re.search(r'\d+(\.\d+)?', s)
            value = match.group()
            value = float(value)

            # return as int if int (prettier print)
            if value == int(value):
                return int(value)

            # return as float if float
            return value
        except:
            return -1 # no number in file

    # extract name from rss feed if known
    def extract_rss_feed_name(self, url):
        if('danke' in url):
            url, name = self.extract_danke_moe(url)
            return True, url, name
        else:
            print('unsupported feed')
            return False, None, dl

    # get latest chapter number on disk
    def get_latest_chapter_num_on_disk(self, dir):

        files = os.listdir(dir)       
        file = sorted(files, key=self.extract_number)[-1]

        result = self.extract_number(file)
        if result == int(result):
            return int(result)  # int prints prettier
        return result # float

    # parse feed, rss or mangadex
    def parse_feed(self, source, combine):

        # if danke, translate to rss
        if('danke.moe' in source and 'rss' not in source):
            source = source.replace('https://danke.moe/read/manga/','https://danke.moe/read/other/rss/').strip('/')

        success = False
        result = None
        name = None
        did_work = False
        
        # supported known types
        if('mangadex' in source):
            result, name, did_work, author = self.parse_mangadex(source)
            success = True
        elif('rss' in source):
            result, name, did_work, author = self.parse_rss_feed(source)
            success = True
        else: 
            print(f'unsupported feed: {source}')
            success = False

        # combine result into single pdf if requested
        if(combine) and (did_work or not len(glob.glob(f'tmp/{name}/{name}*combo.pdf')) > 0):
            self.combine(result, author)
        elif combine:
            print('  ✓ combo pdf exists')

        # convert from cbz to pdf
        if not combine:
            self.convert_to_pdf(result, author)
        
        return success, result, name

    # parse mangadex with MangaDex.py - do not log in
    def parse_mangadex(self, source):
        did_work = False
        guid = None
        author = ''

        # extract manga GUID
        pattern = r"/mangadex/(?P<guid>[\w-]+)/?"
        match = re.search(pattern, source)
        if match:
            guid = match.group("guid")
        else:
            pattern = r"/title/(?P<guid>[\w-]+)/?"
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
        if(len(manga.author) > 0):
            author = manga.author[0].name

        # print title/type
        print()
        key = 'en'
        if not 'en' in manga.title:
            if 'ja-ro' in manga.title:
                key = 'ja-ro'
            else:
                # first value in dictionary of title
                key = next(iter(manga.title))

        if manga.type == None:
            print(manga.title[key], f'- mangadex')
        else:    
            print(manga.title[key], f'- mangadex - {manga.type}')
        tmp_dir = f"tmp/{manga.title[key]}"

        # print truncated description
        desc = manga.desc['en'][:300].rstrip()
        if len(manga.desc['en']) > 300:
            desc += " [...]"
        wrapped_desc = textwrap.fill(desc, width=80)
        indented_desc = textwrap.indent(wrapped_desc, '  ')

        # print tags
        tag_output = ''
        for tag in manga.tags:
            tag_output += tag.name['en'] + ', '
        tag_output = tag_output.rstrip(', ')
        print(' ', f'({tag_output})')

        print('  ~~~~~')
        print(indented_desc)
        print('  ~~~~~')

        # get latest chapter remote and on disk
        latest_chapter_remote = None
        latest_chapter_num_on_disk = -1
        try:
            latest_chapter_num_on_disk = self.get_latest_chapter_num_on_disk(tmp_dir)
        except Exception as e:
            # this is ok, may not exist on disk yet
            latest_chapter_num_on_disk = -1

        # print cache info
        print(f'  ✓ cache: {latest_chapter_num_on_disk}')

        # sort chapters by newest to earliest 
        # (unlike rss mangadex order may be incoherent - with multiple languages and authors)
        chapters = reversed(sorted(manga.get_chapters(), key=self.extract_number))

        # for every chapter
        for chapter in chapters:
            if(chapter.language == 'en'):
                
                # largest number is latest chapter on remote
                if latest_chapter_remote is None:
                    latest_chapter_remote = chapter

                # setup cbz file name for download
                tmp_chapter = f"{tmp_dir}/{manga.title['en']} - {chapter.chapter}" # chapter number not volume
                zip_name = f"{tmp_chapter}.cbz"
                chapter_num = self.extract_number(tmp_chapter)

                # download if remote chapter is newer than cached in number
                # because feed may change for same content, do not strictly match the file/feed information
                if chapter_num > latest_chapter_num_on_disk:

                    if not os.path.exists(tmp_chapter):
                        os.makedirs(tmp_chapter)       

                    print(f'  ✓ downloading: {chapter_num}, please wait..')

                    self.summary.append(f"{chapter_num} - {manga.title['en']}")

                    with contextlib.redirect_stdout(io.StringIO()):    
                        downloader.dl_chapter(chapter, tmp_chapter)
                    print(f'  ✓ done: {chapter_num}')

                    self.create_cbz(tmp_chapter)
                    did_work = True

        # up to date
        # matching local to remote
        if not did_work:
            print('  ✓ remote:', latest_chapter_remote.chapter)

        return tmp_dir, manga.title['en'], did_work, author

    # parse rss feed
    def parse_rss_feed(self, source):
        # Parse the RSS feed
        feed = feedparser.parse(source)

        did_work = False
        author = ''

        # Print the feed information
        print()
        if('danke.moe' in feed.feed.link):
            print(f'{feed.feed.title} - danke.moe')
        else:    
            print(f'{feed.feed.title} - {feed.feed.link}')

        tmp_dir = f'tmp/{feed.feed.title}'  

        # get latest chapter on disk cache
        latest_chapter_num_on_disk = -1
        try:
            latest_chapter_num_on_disk = self.get_latest_chapter_num_on_disk(tmp_dir)
        except Exception as e:
            # this is ok, may not exist on disk yet
            latest_chapter_num_on_disk = -1

        print(f'  ✓ cache: {latest_chapter_num_on_disk}')

        # Print each entry in the feed
        for entry in feed.entries:

            # print(' ', entry.title) #entry.link
            # get author within reason
            try:
                author = re.search(r'https://twitter\.com/(\w+)', entry.description).group(1)
            except:
                author = ''

            # see if feed is known
            result = self.extract_rss_feed_name(entry.link)
            is_known, dl, name = result
            
            if(is_known):
                
                if not os.path.exists(tmp_dir):
                    os.makedirs(tmp_dir)            

                # setup download name
                filename = os.path.basename(name)
                filepath = os.path.join(tmp_dir, filename)

                current_chapter_num = self.extract_number(filename)

                # download if remote chapter is newer than cached in number
                # because feed may change for same content, do not strictly match the file/feed information
                if current_chapter_num > latest_chapter_num_on_disk:

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

                    self.summary.append(f'{current_chapter_num} - {feed.feed.title}')

        # up to date
        # matching local to remote
        if not did_work:
            match = re.search(r'\d+', feed.entries[0].title)
            if match:
                number = match.group()
                print(f'  ✓ up-to-date: Chapter:', number)
            else:
                print(f'  ✓ up-to-date: Chapter:', feed.entries[0].title)

        return tmp_dir, feed.feed.title, did_work, author

    # print summary
    def print_summary(self):
        print()
        print('~~~~~~~~~~~~~~~~~~~~~')

        # nothing done
        if len(self.summary) == 0 and len(self.synced) == 0:
            print('Done, nothing new.')
            return

        # new downloaded content
        if len(self.summary) > 0:
            print('New content:')
        
        # print downloaded content
        for entry in self.summary:
            print(' ', entry)

        # fully synced to device
        if len(self.summary) == len(self.synced):
            print('Synced to device')
        else:

            # downloaded but not synced
            if len(self.summary) > 0 and len(self.synced) == 0:
                print('Not synced to device')
            # not downloaded but cached was newer than device and was synced
            elif len(self.synced) > 0:
                print('Content missing from device, synced to device')
                for s in self.synced:
                    print(s)
            # unsure if possible, print all
            else:
                print('Downloaded:', self.summary)
                print('Sycned:', self.sycned)