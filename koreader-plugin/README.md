# Manga Library — KOReader plugin

Browse and read your self-hosted manga on a Kobo running KOReader. Talks to the
`manga-ereader-backend` container. There is no built-in server address — set it on
the device under **Server** in the menu, using your backend's LAN address, e.g.
`http://192.168.0.x:8684` (a plain-IP LAN address avoids internal-DNS/TLS issues on
the Kobo). Pages arrive as pre-rendered, downscaled grayscale JPEGs (the backend
transcodes from the source PNG/JPG/WebP/AVIF), and reading progress is written back
to the shared `manga.db`, so the browser webapp and the Kobo stay in sync.

## Features
- Library browser mirroring the webapp's filters: All, Favorites, Reading,
  Downloading, Completed, Hiatus, Archived, Read, Hidden — plus **Browse by tag**.
  A **Reload from server** item re-pulls the library so changes made elsewhere
  (e.g. marked read / progress cleared in the webapp) show up.
- Chapter list per title (numeric order), with a **Continue** shortcut at your saved
  page. Tapping the in-progress chapter offers **Resume** or **Start from beginning**.
- Reader controls:
  - **Tap** left third = previous page, right third = next page.
  - **Swipe** left = next, right = previous.
  - **Pinch / spread** = open a zoomable view (pinch-zoom + pan) of the page.
  - **Center tap** = menu showing the chapter and page count, with previous/next
    chapter, go to page, and close.
  - Physical page-turn keys work on devices that have them.
- Thin progress bar along the bottom of each page.
- **Crop page margins** (default on): the backend trims uniform white/black borders so
  the artwork fills more of the screen. Pages whose art reaches the edge are left as-is
  (nothing is cut). Toggle under Manga Library.
- **Use manga cover as sleep screen** (default on): while you're reading a title, the
  device's sleep/screensaver image is set to that manga's overall cover. Your previous
  screensaver setting is saved and restored when you leave the reader. Toggle under
  Manga Library.
- Automatic chapter-to-chapter advance; reaching the end returns you to the list.
- Reading progress is saved per page turn and on close, and synced to `manga.db`.
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
2. First time: **Manga Library → Server** — enter your backend's address, e.g.
   `http://192.168.0.x:8684`. Use **Test connection** to verify reachability.
   (Opening the library before a server is set will prompt for it.)
3. Optionally set **Preload pages ahead** (0, 1, or 2; default 1).
4. **Manga Library → Open library**, pick a filter or tag, choose a title, then a
   chapter. Tap the center of a page for the menu (close is there); swipe or tap the
   edges to turn pages; pinch to zoom.

WiFi is brought up automatically when you open the library. The device must be on a
network allowed by the Caddy admin/LAN IP rules (home WiFi is covered).
