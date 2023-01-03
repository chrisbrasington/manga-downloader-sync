import feedparser, os, re, requests, shutil, urllib
from tqdm import tqdm
import contextlib, glob, io, sys, textwrap, traceback, zipfile
from PIL import Image
from pdfrw import PdfReader, PdfWriter   
from operator import attrgetter
import json

class Manga:
    def __init__(self, data):
        self.id = data["id"]
        self.tags = data["attributes"]["tags"]
        self.relationships = data["relationships"]
        self.desc = ''
        self.tags = []

        key = 'en'
        if not 'en' in data["attributes"]["title"]:
            if 'ja-ro' in data["attributes"]["title"]:
                key = 'ja-ro'
            else:
                # first value in dictionary of title
                key = next(iter(data["attributes"]["title"]))

        self.title = data["attributes"]["title"][key]

        if 'en' in data['attributes']['description']:
            self.desc = data['attributes']['description']['en']

        for tag in data['attributes']['tags']:
            if 'name' in tag['attributes'] and 'en' in tag['attributes']['name']:
                self.tags.append(tag['attributes']['name']['en'])
    
        for relation in data['relationships']:
            if relation['type'] == 'author':
                self._author_id = relation['id']
            elif relation['type'] == 'artist':
                self._artist_id = relation['id']

    @property
    def type(self):
        if len(self.tags) == 0:
            return ''
        return ', '.join(self.tags)

    @property
    def author(self):
        if not self._author_id:
            return 'unknown'
        return self.get_author(self._author_id)

    @property
    def artist(self):
        if not self._artist_id:
            return 'unknown'
        return self.get_author(self._artist_id)

    def get_author(self, id):
        response = requests.get(
            f'https://api.mangadex.org/author/{id}'
        )
        return response.json()['data']['attributes']['name']

    def to_json(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def __str__(self):

        key = 'en'
        if not 'en' in self.title:
            if 'ja-ro' in self.title:
                key = 'ja-ro'
            else:
                # first value in dictionary of title
                key = next(iter(self.title))

        return f'{self.title}'

# Define a Chapter class
class Chapter:
    def __init__(self, chapter_data):
        self.id = chapter_data['id']
        self.type = chapter_data['type']
        self.volume = chapter_data['attributes']['volume']
        self.chapter = chapter_data['attributes']['chapter']
        self.title = chapter_data['attributes']['title']
        self.language = chapter_data['attributes']['translatedLanguage']
        self.external_url = chapter_data['attributes']['externalUrl']
        self.publish_date = chapter_data['attributes']['publishAt']
        self.readable_date = chapter_data['attributes']['readableAt']
        self.create_date = chapter_data['attributes']['createdAt']
        self.update_date = chapter_data['attributes']['updatedAt']
        self.pages = chapter_data['attributes']['pages']
        self.version = chapter_data['attributes']['version']
        self.relationships = chapter_data['relationships']
        self._images = {}

    @property
    def images(self):
        if not self._images:

            response = requests.get(
                    f'https://api.mangadex.org/at-home/server/{self.id}'
                )

            self._images = response.json()['chapter']['data']
            hash = response.json()['chapter']['hash']

            full_images = []
            for image in self._images:
                full_images.append(f'https://uploads.mangadex.org/data/{hash}/{image}')

            self._images = full_images

        return self._images

    def __str__(self):
        return f'{self.chapter} {self.language} {self.title}'

# utility parser class
class Utility:

    # Private constructor
    def __init__(self):
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

            print('\n', self.extract_number(chapter), end=': ')
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
                        print(f'  converting to pdf... {os.path.basename(pdf_path)}')

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

    # get chapter information
    # very quick due to lazy-loading of images
    def get_chapters(self, manga):

        url = f'https://api.mangadex.org/manga/{manga.id}/feed'
        # print(url)

        # Make the request
        response = requests.get(
            url,
            params={
                'translatedLanguage[]': 'en',
                'order[chapter]': 'desc',
                'limit': 500
            }
        )
        data = response.json()['data']
        chapters = [Chapter(d) for d in data]
        chapters = self.remove_duplicate_chapters(chapters)

        # for c in chapters:
        #     print('  ', c.chapter, c.language, c.title)

        return chapters

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
        response = requests.get(
            f'https://api.mangadex.org/manga/{guid}'
        )
        data = response.json()['data']

        manga = Manga(data)

        # print(manga)
        # print(manga.tags)
        # print(manga.author)
        # print(manga.artist)

        # print title/type
        print()


        if manga.type == None:
            print(manga.title, f'- mangadex')
        else:    
            print(manga.title, f'- mangadex - {manga.type}')
        tmp_dir = f"tmp/{manga.title}"

        # print truncated description
        desc = manga.desc[:300].rstrip()
        if len(manga.desc) > 300:
            desc += " [...]"
        wrapped_desc = textwrap.fill(desc, width=80)
        indented_desc = textwrap.indent(wrapped_desc, '  ')

        # print tags
        # tag_output = ''
        # for tag in manga.tags:
        #     tag_output += tag.name + ', '
        # tag_output = tag_output.rstrip(', ')
        # print(' ', f'({tag_output})')
        # print()

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
        if latest_chapter_num_on_disk == -1:
            print('  x - no cache')
        else:
            print(f'  ✓ cache: {latest_chapter_num_on_disk}')

        # get chapters
        chapters = self.get_chapters(manga)
        latest_chapter_remote = chapters[0]

        # remote
        print('  ✓ remote:', latest_chapter_remote.chapter)

        # for every chapter
        for chapter in chapters:

            # setup cbz file name for download
            tmp_chapter = f"{tmp_dir}/{manga.title} - {chapter.chapter}" # chapter number not volume
            zip_name = f"{tmp_chapter}.cbz"
            chapter_num = float(chapter.chapter)

            # download if remote chapter is newer than cached in number
            # because feed may change for same content, do not strictly match the file/feed information
            if chapter_num > latest_chapter_num_on_disk:

                if not os.path.exists(tmp_chapter):
                    os.makedirs(tmp_chapter)       

                print(f'  ✓ downloading:', chapter.chapter, f'({chapter.language})', chapter.title)

                self.summary.append(f"{chapter_num} - {manga.title}")

                i = 0
                for url in tqdm(chapter.images):
                    i += 1
                    response = requests.get(url)
                    _, file_extension = os.path.splitext(url)
                    # to keep cbz sorted, works well to pad the page number 1 as 001
                    # keeps 001 002 003 004 005 006 007 008 009 010 011 etc. well sorted 
                    open(f"{tmp_chapter}/{str(i).zfill(3)}{file_extension}", "wb").write(response.content)
                    pass

                if chapter_num == int(chapter_num):
                    chapter_num = int(chapter_num)
                print(f'  ✓ done: {chapter_num}')

                self.create_cbz(tmp_chapter)
                did_work = True

        # convert entire dir to pdf (where pdfs do not exist)
        if did_work: 
            self.convert_to_pdf(tmp_dir, manga.author)

        return tmp_dir, manga.title, did_work, manga.author

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

        if latest_chapter_num_on_disk == -1:
            print('  x - no cache')
        else:
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

    # remove duplicate chapters (sometimes mulitple scanlations for English, we're dumbly grabbing the first)
    def remove_duplicate_chapters(self, chapters):
        # Create a set of chapters based on the 'chapter' attribute
        unique_chapters = {c.chapter: c for c in chapters}

        # Return the list of unique chapters, sorted by 'chapter' attribute
        return [v for k, v in sorted(unique_chapters.items(), reverse=True, key=self.extract_number)]