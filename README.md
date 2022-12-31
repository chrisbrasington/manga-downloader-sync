# manga-downloader-sync

## site support

- [danke.moe](https://danke.moe/) (best)
- [mangadex](https://mangadex.org/)
- generic rss feeds maybe ?

## device support

tested with `kobo libra 2` and will work with any device that supports cbz (zip) files

<img src=".img/sample.png" style="width:80%">

## feature 
`sources.txt` can support a flag to combine all chapters into a single file for thos manga that like to be a page or two a chapter

> url, True

## run

Modify `sources.txt` run with python 3

> python program.py  

# output
```
✓ kobo detected
The Tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere Girl Getting Less and Less Tsun Day by Day - danke.moe
  ✓ up-to-date: Chapter: 83
  Syncing to device...
    ✓ The Tsuntsuntsuntsuntsuntsuntsuntsuntsuntsuntsundere Girl Getting Less and Less Tsun Day by Day.cbz (combined)
The Overworked Office Lady's Café Crush - danke.moe
OL-cafe-crush-3.cbz: 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 15.1M/15.1M [00:00<00:00, 458MB/s]
  ✓ OL-cafe-crush-3.cbz
  Syncing to device...
    ✓ OL-cafe-crush-3.cbz
    ✓ OL-cafe-crush-2.cbz
    ✓ OL-cafe-crush-1.cbz
Dark Summoner to Dekiteiru - mangadex
  ✓ up-to-date: Chapter: 1
  Syncing to device...
    ✓ Dark Summoner to Dekiteiru - 1.cbz
```