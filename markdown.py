#!/usr/bin/env python3
import os, re, requests, sys
from classes.parser import Utility 
from classes.parser import Manga

def create_markdown(manga, folder, url):

    url = url.split(',')[0]
    # if not existing, create markdown folder
    # create markdown file of manga.title
    markdown_folder = "markdown"

    if folder is not None:
        markdown_folder += f'/{folder}'

    markdown_file = f"{manga.title}.md"

    if not os.path.exists(markdown_folder):
        os.makedirs(markdown_folder)

    dict = manga.to_dict()

    cover = manga.get_cover()
    thumbnail = f'{cover}.256.jpg'

    print(os.path.join(markdown_folder, markdown_file))
    with open(os.path.join(markdown_folder, markdown_file), 'w') as file:
        file.write('---\n')
        for key, value in dict.items():
            if key == 'relationships':
                continue
            if key == 'desc':
                value = (value+"").replace('\n',' ')
                value = value.replace("'", "''")
                value = f"'{value}'"
                print(value)
            file.write(f"{key}: {value}\n")
        file.write(f'author: {manga.author}\n')
        file.write(f'coverUrl: {cover}\n')
        file.write(f'thumbnail: {thumbnail}\n')
        file.write(f'url: {url}\n')
        file.write('---\n')
        # Write additional information about the manga as needed

        dataview = '''
```dataviewjs
const query = `
TABLE WITHOUT ID
	("![thumbnail|100](" + thumbnail + ")") as Cover,
	"#### [["+file.name+"|"+title+"]]" + (" [](" + url + ")") as "Manga",
    author as "Author"

WHERE
	file.name = this.file.name
`
dv.execute(query)
dv.container.classList.add("cards")
```
'''
        file.write(dataview)

    # https://mangadex.org/covers/a69377ee-b842-45f8-983b-0b523b695880/669050f0-90d6-4c94-a9f0-0616983e4627.jpg.512.jpg


def extract_guid(line):
    # Define the regular expression pattern to match the GUID
    pattern = r'([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})'

    # Use re.search to find the first match in the line
    match = re.search(pattern, line)

    # If a match is found, return the GUID
    if match:
        return match.group(1)

    # If no match is found, return None or raise an exception, depending on your requirements
    return None

# Get the file path from the command line arguments
file_path = sys.argv[1]

folder = file_path.split('/')[-1].split('.')[0]

# Read each line from the file
with open(file_path, 'r') as file:

    for line in file:
        print(line.replace('\n',''))
        # Extract the GUID from the line
        guid = extract_guid(line)

        # Serialize manga to string indented and print
        utility = Utility.instance()
        response = requests.get(f'https://api.mangadex.org/manga/{guid}')
        
        data = response.json()['data']
        manga = Manga(data)

        # Perform further actions with the manga object if needed
        # print(manga.title)
        create_markdown(manga, folder, line)

