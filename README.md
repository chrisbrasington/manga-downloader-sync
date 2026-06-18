# manga-kobo

Scheduled manga downloader with a web library and a native KOReader reader. Three Docker containers share a SQLite database and a mounted volume of downloaded files.

## What it does

**Downloader** (`manga-downloader`) runs on a schedule, fetches new chapters from MangaDex and danke.moe, converts them to PDF, and optionally syncs to a Kobo e-reader.

**Webapp** (`manga-webapp`) provides a browsable library with cover art, reading filters, and admin tools — all in a browser. Port `8681`.

**E-reader backend** (`manga-ereader-backend`) is a small device-facing API for the KOReader plugin: it transcodes pages to downscaled grayscale JPEG for e-ink and shares reading progress with the webapp through `manga.db`. Port `8684`. See [`koreader-plugin/README.md`](koreader-plugin/README.md).

## Sources

- [MangaDex](https://mangadex.org/)
- [danke.moe](https://danke.moe/)

---

## Running

```bash
docker compose up -d
```

Webapp is available on port `8681`.

---

## Downloader

```
python program.py            # scheduled run — downloads all active manga
python program.py -u <URL>   # single download (for testing)
python program.py -f <path>  # convert a CBZ file or directory to PDF
```

Manga sources are managed through the webapp or directly in `manga.db`. The downloader reads the `active` entries and skips anything marked `completed`, `hiatus`, or `archived`.

When MangaDex reports a series as completed, the downloader automatically marks it as such and stops checking it.

The downloader pins the download folder to the title stored in the database. If MangaDex later changes a title, it won't create a second folder — it keeps downloading into the original one.

---

## Webapp

`http://localhost:8681`

### Library

Grid of all manga with cover thumbnails, status badges, and last chapter number.

**Filters:** All · ⭐ Favorites · Downloading · Completed · Hiatus · Archived · ✓ Read · 👁 Hidden

Read and Hidden work like soft filters — entries tagged with either only appear when that filter is active. All other filters suppress them.

**Per-manga panel** (click any card):
- Chapter list with read and download links
- URL bar — shows the source URL, editable. "Edit" to correct a bad paste. "🔍 Find" searches MangaDex by title and auto-fills the URL.
- **🖼 Cover** — fetches all available covers from MangaDex, displays a visual picker. Select one to save it as the thumbnail.
- **✓ Read / 👁 Hide / 🗑 Delete** — panel footer actions. Delete shows the exact `rm -rf` command before confirming.

### Admin

`http://localhost:8681/admin`

- **Add manga** — paste a MangaDex or danke.moe URL
- **Scan tmp/ for Untracked** — finds folders on disk not in the database, looks each up on MangaDex, adds them as `archived`
- **Fetch All Thumbnails** — bulk-fetches missing cover art from MangaDex
- **♻️ Find Duplicates** — compares all titles with fuzzy matching (normalizes subtitle separators like ` - `, `:`, `-…-`). Shows pairs with similarity ≥ 85%, recommends keeping the entry with more files. Confirm shows the exact folder path and `rm -rf` command before deleting.

---

## Database

`manga.db` — SQLite with WAL mode. Replaces the old `sources.txt`, `completed.txt`, `hiatus.txt`, `ignore.txt`, and related config files.

**Manga statuses:** `active` (downloading) · `completed` · `hiatus` · `archived` (on disk, not downloading)

**Manga flags:** `favorited` · `read` · `hidden`

Schema is forward-compatible — new columns are added via `ALTER TABLE ... ADD COLUMN` with defaults, so the database survives container rebuilds without migration.

---

## Docker layout

```
manga-kobo/
  manga.db          # shared database
  tmp/              # downloaded manga (one folder per series)
  thumbnails/       # cover art cache (manga_id.jpg)
  ereader_cache/    # transcoded grayscale page cache (e-reader backend)
```

```yaml
services:
  manga:              # container_name: manga-downloader — runs python program.py on a schedule
  webapp:             # container_name: manga-webapp — FastAPI app, port 8681
  ereader-backend:    # container_name: manga-ereader-backend — KOReader API, port 8684
```

The downloader and webapp mount `manga.db`, `tmp/`, and `thumbnails/`. The e-reader
backend mounts `manga.db` (read-write, for progress) plus `tmp/` and `thumbnails/`
read-only, and its own `ereader_cache/`.

Caddy routes `manga-api.home.chrisincode.com` → `127.0.0.1:8684` for the e-reader backend
(alongside `manga.home.chrisincode.com` → `:8681` for the webapp).

---

## Kobo sync

`python program.py` with a Kobo mounted will sync new PDFs to the device. The sync script (`sync`) can also be run on a client machine to pull from the server and push to the reader over SSH.

```bash
# sync script variables
syncDestination="/run/media/chris/KOBOeReader"
sourceDestination="chris@valhalla:/home/chris/code/manga-kobo"
```

PDF metadata includes the author. A Kobo collection is created per series.
