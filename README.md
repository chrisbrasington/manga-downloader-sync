# manga-downloader-sync

Downloads images (manga) from the web into cbz files, converts to pdf,  and syncs between local cache and a device folder. Cache ensures files will not redownload.

<u>Only syncs newer chapters.</u> If older chapters are deleted from the device, only chapters after the latest chapter on device will be added. If no chapters exist on device, all chapters will be synced to device

# Table of Contents

- [manga-downloader-sync](#manga-downloader-sync)
  - [site support](#site-support)
  - [Usage](#usage)
    - [Arguments](#arguments)
  - [Examples](#examples)
  - [chapter number matching](#chapter-number-matching)
    - [sources](#sources)
  - [device support](#device-support)
  - [features](#features)
    - [auto-collections](#auto-collections)
  - [summary of download/sync](#summary-of-downloadsync)
  - [author](#author)
  - [run](#run)
  - [sample sources](#sample-sources)
  - [language](#language)
  - [output](#output)
  - [server/client usage](#serverclient-usage)


## site support

- [mangadex](https://mangadex.org/)
- [danke.moe](https://danke.moe/)

## Usage
`python program.py [-h] [-u URL] [-a [ADD]] [-c [COMPLETED]] [-d [HAITUS]]`

## Arguments

    -h, --help: Show help message and exit
    -u URL, --url URL: Url to read from
    -a [ADD], --add [ADD]: Add url to sources.txt
    -c [COMPLETED], --completed [COMPLETED]: Use completed.txt
    -d [HAITUS], --haitus [HAITUS]: Use dead haitus.txt
    -f [FILE], --file [FILE]: Convert individual file or directory to PDF

All arguments are optional. If no arguments are provided, the program will use the default ongoing source file (sources.txt).

If the -u argument is provided, the program will download the manga from the given url.

If the -a argument is provided with a url, the program will add the url to the sources file.

If any of the -o, -c, or -d arguments are provided, the program will use the corresponding source file instead of the default ongoing file.

If the -f argument is provided with a file or directory, the program convert to PDF.

## Examples

Download manga from a url:

`python program.py -u https://example.com/manga/1`

Add a url to the sources file:

`python program.py -u https://example.com/manga/1 -a`

Use the completed source file:

`python program.py -c`

Use the dead haitus source file:

`python program.py -d`

Convert file to PDF:

`python program.py -f path_to_file.cbz`

Convert directory to PDF:

`python program.py -f path_to_files`

## chapter number matching

Even if the feed changes, the chapter number is attempted to be extracted from the feed. This will not redownload cached chapter numbers even if the file name would be different.

### sources
`sources.txt` can support a flag to combine all chapters into a single file for those manga that like to be a page or two a chapter

> url, True

Or keeping as separate chapters..

> url

## device support

tested with `kobo libra 2` and will work with any device that supports pdf or cbz (zip) files

<img src=".img/sample.png" style="width:100%">

<img src=".img/sample2.jpg" style="width:100%">

## features

### auto-collections

cbz/pdf doesn't seem to support a series metadata tag, I do create a user collection of the manga.

<img src=".img/collection1.png" style="width:50%">

<img src=".img/collection2.png" style="width:50%">

### summary of download/sync

Summary will display both download and synced information. If device is absent, will inform. If only sync happens, will inform.

### author

Author is added to PDF metadata

## run

>  pip install -r requirements.txt       

Modify `sources.txt` run with python 3

> python program.py  

## sample sources

> Note: `mangadex` is looking for the GUID out of the url

```
https://danke.moe/read/manga/the-tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere-girl/, True
https://danke.moe/read/manga/OL-cafe-crush/
https://mangadex.org/title/e5148679-29de-4fff-b1a1-c77c44c41d5a/crest-of-the-stars
```

## language

Hardcoded to `en` atm, and pretty much the first non-external source

## output
```
✓ kobo detected

The Tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere Girl Getting Less and Less Tsun Day by Day - mangadex
   ✓ cache: 84        ✓ remote: 85          downloading: 84 to 85.0
100%|█████████████████████████████████████████████████████████████████████████████████████████████████| 2/2 [00:01<00:00,  1.20it/s]
   x device: 84      
The Overworked Office Lady's Café Crush - danke.moe
   ✓ cache: 3         ✓ remote: 3         ✓ device: 3      
~~~~~~~~~~~~~~~~~~~~~
Content missing from device, synced to device
The Tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere Girl Getting Less and Less Tsun Day by Day - 85.pdf
```

## docker server + client-sync usage

For non-server usage:

You can use `./config` directly which is default behavior of running the program. It assumes you are running the application locally without a server.

For server usage:

1. On the server, add the necessary sources for manga content. This will populate the `./config` folder (sources.txt) by running the program.
2. Use the `./deploy` script to build a Docker image with the provided Dockerfile and run a container named `manga-downloader`. This container will have two folders mounted: `tmp` for downloads and `config` for configuration. The `config` folder can be edited outside the container.

For client usage (syncing to e-reader):

Modify the `sync` script with the following variables:

```bash
syncDestination="/run/media/chris/KOBOeReader" # Replace this with the path to your e-reader destination
sourceDestination="chris@valhalla:/home/chris/code/manga-kobo" # Replace this with the path to your server's manga-kobo directory
```

Running the sync command will attempt to mount the server's download and config folders locally. It won't download content as it assumes you have an auto-downloader already running. The command will move content from the server to your e-reader destination (syncDestination). After usage, these folders will be unmounted. For smooth operation, it's recommended to set up passwordless SSH to avoid prompts.

