# manga-downloader-sync

Downloads images (manga) from the web into cbz files, converts to pdf,  and syncs between local cache and a device folder. Cache ensures files will not redownload.

<u>Only syncs newer chapters.</u> If older chapters are deleted from the device, only chapters after the latest chapter on device will be added. If no chapters exist on device, all chapters will be synced to device

## site support

- [danke.moe](https://danke.moe/) (best)
- [mangadex](https://mangadex.org/)
- generic rss feeds maybe ?

## device support

tested with `kobo libra 2` and will work with any device that supports cbz (zip) files

<img src=".img/sample.png" style="width:100%">

## features
`sources.txt` can support a flag to combine all chapters into a single file for thos manga that like to be a page or two a chapter

> url, True

## run

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

Hardcoded to `en` atm

## output
```
✓ kobo detected
The Tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere Girl Getting Less and Less Tsun Day by Day - danke.moe
the-tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere-girl-83.cbz: 100%|██████████████████████████████████████████████████████████████████████| 5.73M/5.73M [00:00<00:00, 525MB/s]
  ✓ the-tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere-girl-83.cbz
  converting to pdf... tmp/The Tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere Girl Getting Less and Less Tsun Day by Day/the-tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere-girl-83.pdf
  Syncing to device...
  Latest chapter on device: 82
    ✓ the-tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere-girl-83.pdf
The Overworked Office Lady's Café Crush - danke.moe
  ✓ up-to-date: Chapter: 3
  Syncing to device...
  Latest chapter on device: 3
  [...]
```

more information from mangadex:
```
Isekai Nihon - mangadex - shounen
  (Monsters, Action, Romance, Survival, Adventure, Post-Apocalyptic, Magic, Isekai, Gore, Drama, Fantasy)
  ~~~~~
  As two worlds collide into one, a fateful counter between the "killer hero" and
  the "elf princess from another world" has led to a great adventure to defeat the
  even greater evil!
  ~~~~~
  ✓ up-to-date: Chapter: 1
  Syncing to device...
  Latest chapter on device: 2
```