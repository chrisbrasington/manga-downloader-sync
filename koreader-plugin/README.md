# Manga Library — KOReader plugin

Browse and read your self-hosted manga on a Kobo running KOReader. Talks to the
`manga-ereader-backend` container. Default server is the plain-IP LAN address
`http://192.168.0.11:8684` (avoids internal-DNS/TLS issues on the Kobo); change it
under **Server** in the menu — e.g. to `https://manga-api.home.chrisincode.com`.
Pages arrive as pre-rendered, downscaled grayscale JPEGs (the backend transcodes
from the source PNG/JPG/WebP/AVIF), and reading progress is written back to the
shared `manga.db`, so the browser webapp and the Kobo stay in sync.

## Features
- Library browser mirroring the webapp's filters: All, Favorites, Reading,
  Downloading, Completed, Hiatus, Archived, Read, Hidden — plus **Browse by tag**.
- Chapter list per title with a "Continue" shortcut at your saved page.
- Tap-zone reader: left third = previous page, right third = next page, center =
  menu (previous/next chapter, go to page, close). Physical page-turn keys work on
  devices that have them.
- Automatic chapter-to-chapter advance at the end of a chapter.
- Configurable **preload-ahead** (0/1/2 pages, default 1) for snappy page turns.

## Install
1. Connect the Kobo by USB; it mounts as a drive.
2. Copy the `mangalibrary.koplugin/` folder into the KOReader plugins directory on
   the device:

   ```
   /mnt/onboard/.adds/koreader/plugins/mangalibrary.koplugin/
   ```

   (Plugins are just folders dropped in here. Keep the `.koplugin` suffix.)
3. Eject and unplug.

## Run
1. In KOReader, open the top menu → **Tools** (wrench icon) → **Manga Library**.
   - If it doesn't appear, fully restart KOReader (top menu → exit/restart);
     plugins are loaded at startup.
2. First time: **Manga Library → Server** — confirm it is `http://192.168.0.11:8684`
   (change if your setup differs). Use **Test connection** to verify reachability.
3. Optionally set **Preload pages ahead** (0, 1, or 2; default 1).
4. **Manga Library → Open library**, pick a filter or tag, choose a title, then a
   chapter. The reader resumes at your last-read page when there is saved progress.

WiFi is brought up automatically when you open the library. The device must be on a
network allowed by the Caddy admin/LAN IP rules (home WiFi is covered).
