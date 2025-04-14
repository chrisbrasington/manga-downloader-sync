#!/usr/bin/env python3
import os, re, requests, sys
from classes.parser import Utility 
from classes.parser import Manga

def create_markdown(manga, url):

    markdown_folder = os.path.expanduser("~/obsidian/_inbox")
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', manga.title)[:255]
    markdown_file = f"{safe_title}.md"

    if not os.path.exists(markdown_folder):
        os.makedirs(markdown_folder)

    dict = manga.to_dict()

    cover = manga.get_cover()
    thumbnail = f'{cover}.256.jpg'

    file_path = os.path.join(markdown_folder, markdown_file)
    print(f"Writing to: {file_path}")
    
    with open(file_path, 'w') as file:
        file.write('---\n')
        for key, value in dict.items():
            if key == 'relationships' or key == 'data':
                continue
            if key == 'desc':
                value = (value + "").replace('\n',' ').replace("'", "''")
                value = f"'{value}'"
                file.write(f"description: {value}\n")
            else:
                file.write(f"{key}: {value}\n")
        file.write(f'author: {manga.author}\n')
        file.write(f'coverUrl: {cover}\n')
        file.write(f'thumbnail: {thumbnail}\n')
        file.write(f'url: {url}\n')
        file.write('tags: manga')
        file.write('\n---\n')

def extract_guid(url):
    # Extract GUID from the URL using regex
    pattern = r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'
    match = re.search(pattern, url)
    return match.group(1) if match else None

# Check if URL is provided
if len(sys.argv) < 2:
    print("Usage: script.py <manga URL>")
    sys.exit(1)

url = sys.argv[1]
guid = extract_guid(url)

if not guid:
    print("No valid GUID found in the URL.")
    sys.exit(1)

# Fetch data and create markdown
utility = Utility.instance()
response = requests.get(f'https://api.mangadex.org/manga/{guid}')
data = response.json()['data']
manga = Manga(data)
create_markdown(manga, url)
