import feedparser, os, re, requests, shutil, urllib
from tqdm import tqdm
import contextlib, glob, io, sys, textwrap, traceback, zipfile
from PIL import Image
from pdfrw import PdfReader, PdfWriter   
from operator import attrgetter
import colorama, json
import builtins, traceback
# from memedetect import is_comic_book
import sqlite3, datetime, uuid, json
from classes.cache import Cache
from collections import defaultdict

class Manga:
    def __init__(self, data):
        # print(json.dumps(data, indent=4))
        self.id = data["id"]
        self.tags = data["attributes"]["tags"]
        self.relationships = data["relationships"]
        self.desc = ''
        self.tags = []
        self.status = data["attributes"]["status"]
        self.demographic = data['attributes']['publicationDemographic']
        self.data = data

        key = 'en'
        if not 'en' in data["attributes"]["title"]:
            if 'ja-ro' in data["attributes"]["title"]:
                key = 'ja-ro'
            else:
                # first value in dictionary of title
                key = next(iter(data["attributes"]["title"]))

        # make title path safe early
        self.title = data["attributes"]["title"][key].replace('?','_')

        # if self.status == 'completed':
        #     print()
        #     print()
        #     print(f'completed!!!!!!!!!! {self.title}')

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
    
    def get_status_completed(self):
        return self.status == 'completed'
    
    # use ja-ro from altTitles
    def get_japanese_title(self):
        altTitles = self.data['attributes']['altTitles']
        first_ja = next((item['ja-ro'] for item in altTitles if 'ja-ro' in item), None)

        if first_ja is not None:
            return first_ja
        return self.title

    def get_english_title(self):

        # first see if title en exists in data
        if 'en' in self.data['attributes']['title']:
            if self.data['attributes']['title']['en'] is not None:
                english_title = self.data['attributes']['title']['en']

                # Extract the first two words of both titles
                english_first_two_words = ' '.join(english_title.split()[:2])
                japanese_first_two_words = ' '.join(self.get_japanese_title().split()[:2])

                # If the first two words match, do not return the english_title
                if english_first_two_words != japanese_first_two_words:
                    return english_title

        altTitles = self.data['attributes']['altTitles']
        first_en = next((item['en'] for item in altTitles if 'en' in item), None)

        if first_en is not None:
            return first_en
        return self.title
    
    #  "English Title (Japanese Title)"
    def get_combined_title(self):
        result = f"{self.get_english_title()} ({self.get_japanese_title()})"

        # make path safe
        result = result.replace(':','')
        result = result.replace('?','')
        result = result.replace('.','')
        result = result.replace('"','')
        return result

    def get_author(self, id):
        response = requests.get(
            f'https://api.mangadex.org/author/{id}'
        )
        return response.json()['data']['attributes']['name']

    def to_dict(self):
        return self.__dict__

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
    
    def get_cover(self):
        if self.id:
            response = requests.get(
                f'https://api.mangadex.org/cover?manga%5B%5D={self.id}'
            )
            filename = response.json()['data'][0]['attributes']['fileName']
            return f'https://mangadex.org/covers/{self.id}/{filename}'

# Define a Chapter class
class Chapter:
    def __init__(self, chapter_data, manga = None):
        self.id = chapter_data['id']
        self.type = chapter_data['type']
        self.volume = chapter_data['attributes']['volume']
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
        self.scanlation_group = next(
            (rel['id'] for rel in self.relationships if rel.get('type') == 'scanlation_group'),
            None
        )
        self._images = {}

        # oneshot detection
        self.chapter = 1 if chapter_data['attributes']['chapter'] is None else chapter_data['attributes']['chapter']
        if chapter_data['attributes']['chapter'] is None and self.title is None and manga is not None:
            self.title = manga.title          

        # print(self.title)
        # print(self.chapter)
        # print(self.language)
        # print(self.scanlation_group)
        # print(chapter_data)
        # print('~~~~~~~~')

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
        print(self.title)
        return f'{self.chapter} {self.language} {self.title}'

# utility parser class
class Utility:

    # Global set to store ignored scanlation groups
    IGNORED_SCANLATION_GROUPS = set()

    pad_value = 20

    # Private constructor
    def __init__(self):
        global print
        self.summary = []
        self.synced = []

        colorama.init()

        # override print for tabbed print
        # print = self.print_tabbed

    # Static instance method
    @staticmethod
    def instance():
        if not hasattr(Utility, "_instance"):
            Utility._instance = Utility()
        return Utility._instance

    # add url to file
    def add_url_to_file(self, url, file_path):

        # Check if file exists, create it if it doesn't
        if not os.path.isfile(file_path):
            with open(file_path, 'w'):
                pass

        # Check if url already exists in file
        with open(file_path, 'r') as f:
            lines = f.readlines()
        if url+'\n' in lines:
            print(f"URL '{url}' already exists in file.")
            return

        # If url doesn't exist, add it to the top of the file and save it
        with open(file_path, 'w') as f:
            f.write(url+'\n')
            f.writelines(lines)

        print(f"Added URL '{url}' to file '{file_path}'.")

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

            # print(chapter)
            # print(self.extract_number(chapter))

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

    # convert directory from cbz to pdf
    def convert_dir_to_pdf(self, dir, author=''):

        # if combo requested, use {title}.cbz
        combo_file = f'{dir}.cbz'
        
        for root, dirs, files in os.walk(dir):
            # Add the files to the ZIP file
            for file in sorted(files, key=self.extract_number):
                # print(file)
                # skip over existing pdfs
                if 'pdf' not in file:
                    self.convert_file_to_pdf(os.path.join(dir, file), author)

    # convert individual file from cbz to pdf  
    def convert_file_to_pdf(self, file, author=''):

        # get cbz and pdf name
        file_path = file
        pdf_path = file_path.replace('cbz','pdf')

        # if pdf not existing, convert
        if not os.path.exists(pdf_path):

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

    # create kobo collection
    def create_kobo_collection(self, sync_dir, title):

        sync_dir = sync_dir.replace('"','')
        sync_dir = sync_dir.replace(':','')
        title = title.replace('"','')
        title = title.replace(':','')

        # Define the target directory and collection name
        target_dir = 'file:///mnt/onboard/manga/' + os.path.basename(title.rstrip('.'))
        
        target_dir = target_dir.replace('"', '')
        target_dir = target_dir.replace(':', '')
        
        collection_name = os.path.basename(target_dir)

        # Connect to the SQLite database and make a backup
        db = os.path.join(os.path.dirname(sync_dir), ".kobo", 'KoboReader.sqlite')

        if os.path.exists(db):
            conn = sqlite3.connect(db)
            backup_dir = "backup/kobo"
            os.makedirs(backup_dir, exist_ok=True)
            backup_filename = f'{backup_dir}/KoboReader_backup_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.sqlite'
            shutil.copy(db, backup_filename)

            # Check if the shelf already exists
            cursor = conn.cursor()
            cursor.execute('SELECT Id FROM Shelf WHERE InternalName = ?', (collection_name,))
            row = cursor.fetchone()

            now = datetime.datetime.utcnow()
            formatted_time = now.strftime('%Y-%m-%dT%H:%M:%SZ')

            if row is not None:
                # Shelf already exists, do nothing
                # print(f'Shelf {collection_name} already exists.')
                shelf_id = row[0]
            else:
                # Insert a new row into the Shelf table for the collection
                shelf_values = (formatted_time, collection_name, collection_name, formatted_time, collection_name, 'UserTag', 'false', 'true', None, '', '')
                cursor.execute('INSERT INTO Shelf (CreationDate, Id, InternalName, LastModified, Name, Type, _IsDeleted, _IsVisible, _IsSynced, _SyncTime, LastAccessed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', shelf_values)
                shelf_id = cursor.lastrowid
                # print(f'Shelf {collection_name} created.')

            count = 0

            # Iterate over the PDF files in the source directory and insert a new row into the ShelfContent table for each file
            for filename in os.listdir(os.path.join(sync_dir, title)):
                if filename.endswith('.pdf'):

                    filename = filename.replace('"','')
                    filename = filename.replace(':','')

                    count += 1
                    content_id = os.path.join(target_dir, filename)
                    # Check if the content already exists
                    cursor.execute('SELECT ContentId FROM ShelfContent WHERE ContentId = ?', (content_id,))
                    row = cursor.fetchone()

                    if row is None:
                        # Insert a new row into the ShelfContent table for the file
                        content_values = (collection_name, content_id, formatted_time, 'false', 'false')
                        cursor.execute('INSERT INTO ShelfContent (ShelfName, ContentId, DateModified, _IsDeleted, _IsSynced) VALUES (?, ?, ?, ?, ?)', content_values)
                        # print(f'Content {content_id} added to shelf.')

            # Commit the changes to the database and close the connection
            conn.commit()
            conn.close()
            print(f'    ✓ kobo collection: {count} items', end='')
        else:
            print('    x - kobo collection: no device found', end='\n')
            print(db)

    # extract rss name from danke feed
    def extract_danke_moe(self, url):
        dl = url.split("read/manga/")[-1].strip('/')
        dl = dl.rsplit("/", 1)[0]
        base = 'https://danke.moe/api/download_chapter/'
        return f'{base}{dl}', f'{dl.replace("/","-")}.cbz'

    # extract number from chapter metadata or filename
    def extract_number(self, s):
        
        original = s
        # print(s)
        # Chapter class is known and can sort by float value
        if type(s) == Chapter:
            try:
                return float(s.chapter)
            except:
                fixed = s.chapter
                # this is the worst fucking code I've ever written
                # but f `cosmic censhorship` using char in a chapter float num
                if s.chapter.endswith('a'):
                        fixed = s.chapter.replace('a','.1')
                elif s.chapter.endswith('b'):
                        fixed = s.chapter.replace('b','.2')
                elif s.chapter.endswith('c'):
                        fixed = s.chapter.replace('c','.3')
                elif s.chapter.endswith('d'):
                        fixed = s.chapter.replace('d','.4')
                elif s.chapter.endswith('e'):
                        fixed = s.chapter.replace('e','.5')
                s.chapter = fixed
                return float(fixed)

        # get largest chapter out of a combo file
        if 'combo' in s:
            return -1
            # parts = s.split("-combo")[0].split("-")
            # number = re.findall(r'\d+', parts[-1])[0]
            # print(s, number)
            # return number # -1

        if type(s) == tuple:
            s = s[0]   
        if type(s) == int:
            return s 
        if type(s) == float:
            return s        
        
        if len(s.split('-')) > 1:
            s = s.replace(s.split('-')[0], '')  

        s = ''.join(c for c in s if c.isnumeric() or c == '.' or c == '-')
        s = s.replace('-', '.')

        # trim any leading periods
        s = re.sub("^\\.+", "", s)
        # trim any trailing periods
        s = re.sub("\\.+$", "", s)
        # print(s)

        try:

            value = float(s)

            if str(value).endswith('.0'):
                value = int(value)

            return value
           
        except:
            # print()
            # print(f'critical error: {original} as {s}')
            # # traceback.print_tb(limit=None, file=None)
            # sys.exit()
            return -1 # no number in file

    # extract number from combo file
    def extract_number_from_combo(self, s):
        
        split_str = s.split('-combo')[0].split('-')[-1]
        return int(split_str)

    # extract name from rss feed if known
    def extract_rss_feed_name(self, url):
        if('danke' in url):
            url, name = self.extract_danke_moe(url)
            return True, url, name
        else:
            print(f'\n {url} - unsupported feed')
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

        # print(data)

        chapters = [Chapter(d, manga) for d in data]

        chapters = self.remove_duplicate_chapters(chapters)

        # remove ignored chapters
        ignored_ids = self.load_ignored_chapters()
        # Print chapters being ignored
        for c in chapters:
            if c.id in ignored_ids:
                print(f"Ignoring chapter: {c.id} {c}")
        chapters = [c for c in chapters if c.id not in ignored_ids]

        # for c in chapters:
        #     print('  ', c.chapter, c.language, c.title)

        return chapters

    # get all urls in a collection from file
    def get_collection(self, source):
        with open(str(source), 'r') as f:
            urls = [url.strip() for url in f.readlines()]

        # remove empty strings
        urls = list(filter(None, urls))

        return urls

    # get latest chapter number on disk
    def get_latest_chapter_num_on_disk(self, dir, title=''):

        raw_files = os.listdir(dir)       
        files = []

        for f in raw_files:
            files.append(f.replace(title, ''))

        try:
            files = sorted(files, key=self.extract_number)
        except:
            print('critical sorting error')
            sys.exit()

        # verbose chapters on disk
        # for f in files:
        #     if 'cbz' in f:
        #         num = self.extract_number(f)
        #         print(num, end='')
        #         if f != files[-1]:
        #             print(', ', end='')
        # print()

        result = self.extract_number(files[-1])

        if result == int(result):
            return int(result)  # int prints prettier

        return result # float
    
    def get_manga(self, source):
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

        # print(manga.get_english_title())

        return manga

    def load_ignored_chapters(self):
        file_path = "config/ignore.txt"
        try:
            with open(file_path, "r") as f:
                return set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            return set()

    def load_ignored_scanlations(self):
        """Loads ignored scanlation groups from config/ignore_scanlation.txt only once."""
        if not Utility.IGNORED_SCANLATION_GROUPS:  # Load only if empty
            ignore_file = "config/ignore_scanlation.txt"
            if os.path.exists(ignore_file):
                with open(ignore_file, "r", encoding="utf-8") as f:
                    Utility.IGNORED_SCANLATION_GROUPS = {line.strip() for line in f if line.strip()}

    # parse feed, rss or mangadex
    def parse_feed(self, source, combine, sync_only):

        # if danke, translate to rss
        if('danke.moe' in source and 'rss' not in source):
            source = source.replace('https://danke.moe/read/manga/','https://danke.moe/read/other/rss/').strip('/')

        success = False
        result = None
        name = None
        did_work = False
        author = ''

        # supported known types
        if('mangadex' in source):
            result, name, did_work, author, combo_title = self.parse_mangadex(source, sync_only)
            success = True
        elif('rss' in source):
            result, name, did_work, author, combo_title = self.parse_rss_feed(source, sync_only)
            success = True
        else: 
            print(f'\nunsupported feed: {source}', end='')
            success = False

        # combine result into single pdf if requested
        if(combine) and (did_work or not len(glob.glob(f'tmp/{name}/{name}*combo.pdf')) > 0):
            self.combine(result, author)

        # cache = Cache()
        # cache.store_manga_data(name, manga.id, source)
        
        return success, result, name, combo_title

    # parse mangadex with MangaDex.py - do not log in
    def parse_mangadex(self, source, sync_only):
        did_work = False
        guid = None

        manga = self.get_manga(source)

        # print(manga)
        # print(manga.tags)
        # print(manga.author)
        # print(manga.artist)

        # print title/type
        print()

        # hyperlink
        print(manga.title, end=' - ')
        print(f"\u001b]8;;{source}\u001b\\mangadex\u001b]8;;\u001b\\")

        # else:    
            # print(manga.title, f'- mangadex - {manga.type}')
        tmp_dir = f"tmp/{manga.title}"

        # print truncated description
        desc = manga.desc[:300].rstrip()
        if len(manga.desc) > 300:
            desc += " [...]"
        wrapped_desc = textwrap.fill(desc, width=80)
        indented_desc = textwrap.indent(wrapped_desc, '  ')

        # print('  ~~~~~')
        # print(indented_desc)
        # print('  ~~~~~')

        # get latest chapter remote and on disk
        latest_chapter_remote = None
        latest_chapter_num_on_disk = -1
        try:
            latest_chapter_num_on_disk = self.get_latest_chapter_num_on_disk(tmp_dir, manga.title)
        except Exception as e:
            # this is ok, may not exist on disk yet
            latest_chapter_num_on_disk = -1

        # print status
        print(f'     status: {manga.status}')

        if not sync_only:

            # get chapters
            chapters = self.get_chapters(manga)

            if len(chapters) == 0:
                print('No chapters, might be external to mangadex only')
                return tmp_dir, manga.title, False, manga.author
            
            # sort chapters
            chapters = sorted(chapters, key=self.extract_number, reverse=True)

            latest_chapter_remote = chapters[0]

            # print(latest_chapter_remote)

            # for c in chapters:
            #     print(c.title)
            #     print(c.scanlation_group)

            # print cache info
            if latest_chapter_num_on_disk == -1:
                print('  x - no cache'.ljust(self.pad_value), end='')
                # for chapter in chapters:
                #     print(' ', chapter)
            else:
                print(f'    ✓ cache: {latest_chapter_num_on_disk}'.ljust(self.pad_value), end='')

            # remote
            print(f'  ✓ remote: {latest_chapter_remote.chapter}'.ljust(self.pad_value), end='')

            download_print_once = False

            if not os.path.exists(tmp_dir):
                os.makedirs(tmp_dir)

            # for every chapter
            # go from oldest to newest
            # list(reversed(chapters)) or chapters[::-1]
            for chapter in chapters[::-1]:

                # setup cbz file name for download
                tmp_chapter = f"{tmp_dir}/{manga.title} - {chapter.chapter}" # chapter number not volume
                zip_name = f"{tmp_chapter}.cbz"

                chapter_num = float(chapter.chapter)

                # change force_all_download to true if you want old chapters to download 
                #   when new chapters exist on disk
                # otherwise, the app will find the largest chapter number on disk and only
                #   download chapters greater than that
                # force_all_download as True risks duplication from different feeds
                #   as it checks file_name directly not chapter number
                force_all_download = False

                # download if remote chapter is newer than cached in number
                # because feed may change for same content, do not strictly match the file/feed information
                if chapter_num > latest_chapter_num_on_disk or force_all_download:
                    
                    if os.path.exists(f'{tmp_chapter}.cbz'):
                        # print('  ✓ exists:', chapter.chapter, f'({chapter.language})', chapter.title, end='')
                        continue

                    self.summary.append(f"{chapter_num} - {manga.title}")

                    if not download_print_once:
                        start = latest_chapter_num_on_disk
                        end = chapters[0].chapter

                        if latest_chapter_num_on_disk <= 0:
                            start = chapters[-1].chapter

                        print(colorama.Fore.RED + f'    downloading: {start}-{end}'.ljust(self.pad_value) + colorama.Style.RESET_ALL)
                        download_print_once = True

                    
                    if not os.path.exists(tmp_chapter):
                        os.makedirs(tmp_chapter)

                    print(chapter_num)
                    path = ''
                    i = 0

                    # print(chapter.url)
                    # print('abort')
                    # sys.exit()

                    for url in tqdm(chapter.images):
                        i += 1
                        response = requests.get(url)
                        _, file_extension = os.path.splitext(url)
                        # to keep cbz sorted, works well to pad the page number 1 as 001
                        # keeps 001 002 003 004 005 006 007 008 009 010 011 etc. well sorted 
                        path = f"{tmp_chapter}/{str(i).zfill(3)}{file_extension}"
                        open(path, "wb").write(response.content)
                        pass

                    # is_manga, percent = is_comic_book(path)

                    # if not is_manga:
                    #     print('MEME DETECTED!!!')
                    #     # os.remove(path)              
                    # else:
                    #     print('keeping all images')  

                    if chapter_num == int(chapter_num):
                        chapter_num = int(chapter_num)

                    self.create_cbz(tmp_chapter)
                    did_work = True

            # convert entire dir to pdf (where pdfs do not exist)
            if did_work: 
                self.convert_dir_to_pdf(tmp_dir, manga.author)

        cache = Cache()
        cache.store_manga_data(manga.title, manga.id, source)

        return tmp_dir, manga.title, did_work, manga.author, manga.get_combined_title();

    # parse rss feed
    def parse_rss_feed(self, source, sync_only):
        # Parse the RSS feed
        feed = feedparser.parse(source)

        did_work = False
        author = ''

        # Print the feed information
        print()

        # hyperlink
        print(feed.feed.title, end=' - ')
        link = feed.feed.link
        if('danke.moe' in feed.feed.link):
            link = 'danke.moe'
        print(f"\u001b]8;;{source}\u001b\\{link}\u001b]8;;\u001b\\")

        tmp_dir = f'tmp/{feed.feed.title}'  

        # get latest chapter on disk cache
        latest_chapter_num_on_disk = -1
        try:
            latest_chapter_num_on_disk = self.get_latest_chapter_num_on_disk(tmp_dir)
        except Exception as e:
            # this is ok, may not exist on disk yet
            latest_chapter_num_on_disk = -1

        if latest_chapter_num_on_disk == -1:
            print('  x - no cache'.ljust(self.pad_value), end='')
        else:
            print(f'   ✓ cache: {latest_chapter_num_on_disk}'.ljust(self.pad_value), end='')

        # Print each entry in the feed
        for entry in feed.entries:

            # print(' ', entry.title) #entry.link
            # get author within reason
            try:
                author = re.search(r'https://twitter\.com/(\w+)', entry.description).group(1)
            except:
                author = ''

            print(f'    {entry.title}'.ljust(self.pad_value), end='')

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
                print(f'  ✓ remote: {number}'.ljust(self.pad_value), end='')
            else:
                print(f'  ✓ remote: {feed.entries[0].title} ?'.ljust(self.pad_value), end='')

        return tmp_dir, feed.feed.title, did_work, author, feed.feed.title

    # process collection
    def process_collection(self, source, sync_destination, sync_only):

        # Allow source to be either a single string or an array of strings
        if isinstance(source, str):
            source = [source]

        cache = Cache()
        catalog = []

        for s in source:

            try:
                # lines are url comma separated to a bool 1 or 0 for sync
                # if sync only, skip lines with sync false (0)
                if sync_only:
                    if '0' in s.split(',')[-1]:
                        continue

                manga = cache.manga_exists(s)
                if manga.exists:
                    # print(f"Manga with ID {manga.id} exists with title '{manga.title}'")
                    # If manga exists in the cache, add it to the catalog
                    catalog.append(manga)

                # URL parameter is provided
                # print(f"Downloading from {s}")
                known, tmp_dir, title_used, combo_title = self.parse_feed(s, False, sync_only)

                # remove : from title
                title_used = title_used.replace(':','')

                # if not exists sync_destination
                if not os.path.exists(sync_destination):
                    continue

                final_sync_destination = None

                # look for title in first sync_destination + read and second sync_destination
                # the title just has to be contained in the folder name
                for folder in os.listdir(sync_destination + "_reading"):
                    if title_used in folder:
                        # reading_folder = os.path.join(sync_destination + "_reading", folder)
                        title_used = folder
                        # print(f"   \"{title}\" as the modified title")
                        final_sync_destination = os.path.join(sync_destination + "_reading")    
                        break

                if final_sync_destination is None:
                    for folder in os.listdir(sync_destination):
                        if title_used in folder:
                            # reading_folder = os.path.join(sync_destination + "_reading", folder)
                            title_used = folder
                            # print(f"   \"{title}\" as the modified title")
                            final_sync_destination = os.path.join(sync_destination)    
                            break

                if final_sync_destination is None:
                    final_sync_destination = sync_destination 
                    title_used = combo_title

                    if not os.path.exists(os.path.join(sync_destination, combo_title)):
                        os.makedirs(os.path.join(sync_destination, combo_title))

                # print('!!!!!')
                print(f"     {final_sync_destination}/{title_used}")   
                # print(f"     {title_used}")  
                # sys.exit()       

                # Sync to device if the manga is known and the final destination is writable
                if known and os.access(final_sync_destination, os.W_OK):

                    # split on KOBOeReader/
                    subdir = f"   {final_sync_destination}".split('KOBOeReader/')[-1]

                    # print(f"     {subdir}")
                    self.sync(tmp_dir, final_sync_destination, title_used, False)

                    # print('\n\n~~~~~~~~~~')
                    # print(combo_title)
                    # print(subdir)

                    # print title used
                    # print('\n\n!!!!!!!!!!!!')
                    # print(f"     {title_used}")
                    # print(f"     {combo_title}")
                    # print(f"     {manga.get_japanese_title()}")

                    if(title_used != combo_title):
                        # ask the user if they want to move from subdir to combo_title
                        new_target = f"{final_sync_destination}/{combo_title}"

                        # check if the new target exists
                        # if os.path.exists(new_target):
                        #     print(f'\n   {new_target} already exists')

                        # check if manga.url exists in config/ignore_rename.txt
                        # if it does, skip the prompt
                        if os.path.isfile('config/ignore_rename.txt'):
                            with open('config/ignore_rename.txt', 'r') as f:
                                lines = f.readlines()
                            if s+'\n' in lines:
                                # print(f"URL '{s}' exists in file 'config/ignore_rename.txt'. Skipping prompt.")
                                print(f'     (using original name)', end='')
                                continue

                        # ask user to
                        print(f'\n\n   Old name detected', end='')
                        print(f'\n     {final_sync_destination}/{title_used} ->\n     {new_target}')
                        print(f'   Do you want to move? ', end='')
                        answer = input()
                        if answer.lower() == 'y':
                            # print moving 
                            print('   Moving')
                            # move the directory
                            shutil.move(f"{final_sync_destination}/{title_used}", new_target)
                            print('   Moved')
                            # print new location
                            print(f'   {new_target}')
                        elif answer.lower() == 'q':
                            # quit running
                            sys.exit()
                        elif answer.lower() == 'n':
                            # add manga.url to config/ignore_rename.txt
                            
                            # Check if file exists, create it if it doesn't
                            if not os.path.isfile('config/ignore_rename.txt'):
                                with open('config/ignore_rename.txt', 'w'):
                                    pass
                            
                            # Check if url already exists in file
                            with open('config/ignore_rename.txt', 'r') as f:
                                lines = f.readlines()
                            
                            if s+'\n' in lines:
                                print(f"URL '{s}' already exists in file.")
                            else:
                                # If url doesn't exist, add it to the top of the file and save it
                                with open('config/ignore_rename.txt', 'w') as f:
                                    f.write(s+'\n')
                                    f.writelines(lines)
                                
                                print(f"Added URL '{s}' to file 'config/ignore_rename.txt'.")

                    # faster to not create a kobo collection - us KOReader instead
                    # Create a Kobo collection using the final sync destination
                    # self.create_kobo_collection(final_sync_destination, title)
                except ex:
                    print(f'error with {s} in collection')

        # Optionally process catalog entries
        # for manga in catalog:
        #    print(f"Manga with ID {manga.id} exists with title '{manga.title}'")

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
            print(colorama.Fore.GREEN + 'New content:')
        
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
                print(colorama.Fore.GREEN + 'Content missing from device, synced to device')
                for s in self.synced:
                    print(s)
            # unsure if possible, print all
            else:
                print('Downloaded:', self.summary)
                print('Sycned:', self.sycned)

    # remove duplicate chapters (sometimes mulitple scanlations for English, we're dumbly grabbing the first)
    def remove_duplicate_chapters(self, chapters):
        """Removes duplicate chapters, preferring non-ignored scanlations when possible."""
        # Ensure ignored scanlation groups are loaded
        self.load_ignored_scanlations()

        # Group chapters by chapter number
        grouped_chapters = defaultdict(list)
        for c in chapters:
            grouped_chapters[c.chapter].append(c)

        final_chapters = []

        for chapter_num, chapter_list in grouped_chapters.items():
            # If there's only one version, use it
            if len(chapter_list) == 1:
                final_chapters.append(chapter_list[0])
                continue

            # Separate ignored and non-ignored scanlations
            non_ignored = [c for c in chapter_list if c.scanlation_group not in Utility.IGNORED_SCANLATION_GROUPS]
            ignored = [c for c in chapter_list if c.scanlation_group in Utility.IGNORED_SCANLATION_GROUPS]

            if non_ignored:
                # Use the first non-ignored scanlation (since any of them is better than ignored)
                selected = non_ignored[0]
                for ig in ignored:
                    print(f"Ignoring scanlation group {ig.scanlation_group} for chapter {chapter_num} in favor of {selected.scanlation_group}")
            else:
                # No non-ignored scanlation found, keep one ignored version
                selected = ignored[0]
                print(f"Would ignore scanlation group {selected.scanlation_group} for chapter {chapter_num}, but no alternative found.")

            final_chapters.append(selected)

        return sorted(final_chapters, reverse=True, key=self.extract_number)

    # sync to location (ereader)
    def sync(self, tmp_dir, sync_destination, title, combine):
        # Prepare the sync destination path
        sync_dest = os.path.join(sync_destination, title).replace('"', '').replace(':', '')

        # print(f'\nSyncing {title} to {sync_dest}')

        # Ensure the destination directory exists
        if os.access(sync_destination, os.W_OK):
            os.makedirs(sync_dest, exist_ok=True)

            combo_output = None
            device_output = None
            did_work = False

            # Handle combined files if `combine` is True
            if combine:
                combined_files = glob.glob(f'{tmp_dir}/*combo.pdf')
                if combined_files:
                    source_path = combined_files[0]
                    file_name = os.path.basename(source_path)
                    sync_dest_file = os.path.join(sync_dest, file_name)
                    
                    if not os.path.exists(sync_dest_file):
                        # Remove prior combined files
                        for prior_combo in glob.glob(f'{sync_dest}/*combo.pdf'):
                            os.remove(prior_combo)

                        print(f'Copying {file_name}, please wait...')
                        shutil.copy(source_path, sync_dest_file)
                        self.synced.append(file_name)

                    # Extract chapter range for combined file
                    match = re.search(r"-(\d+(\.\d+)?)-(\d+(\.\d+)?)-", file_name)
                    combo_output = f"{match.group(1)}-{match.group(3)}(combo)" if match else f"{file_name}(combo)"

            # Determine the latest chapter on the device
            latest_chapter_num = -1
            try:
                all_device_files = sorted(os.listdir(sync_dest), key=self.extract_number)
                latest_chapter = all_device_files[-1] if all_device_files else None
                if latest_chapter:
                    latest_chapter_num = self.extract_number_from_combo(latest_chapter) if "combo" in latest_chapter else self.extract_number(latest_chapter)
            except Exception:
                device_output = "nothing!"

            if latest_chapter_num != -1:
                device_output = latest_chapter_num

            # Sync files from `tmp_dir` to the device
            pdf_files = sorted(
                glob.glob(f"{tmp_dir}/*.pdf"),
                key=self.extract_number
            )

            for filename in pdf_files:
                current_chapter_num = self.extract_number(filename)

                # Skip chapters already on the device
                if current_chapter_num > latest_chapter_num:
                    sync_dest_file = os.path.join(sync_dest, os.path.basename(filename)).replace('"', '').replace(':', '')

                    # print(current_chapter_num, latest_chapter_num, sync_dest_file)

                    if os.access(sync_destination, os.W_OK) and not os.path.exists(sync_dest_file):
                        os.makedirs(os.path.dirname(sync_dest_file), exist_ok=True)
                        shutil.copy(filename, sync_dest_file)
                        print(f'    ✓ Synced {filename}')
                        self.synced.append(os.path.basename(filename))
                        did_work = True

            # Display results
            char = '✓' if not did_work else 'x'
            result_output = f"   {char} device: {device_output}"
            if combo_output:
                result_output += f" and {combo_output}"

            print(result_output.ljust(self.pad_value) if not did_work else colorama.Fore.RED + f"    x device" + colorama.Style.RESET_ALL, end='')
