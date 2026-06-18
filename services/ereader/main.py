"""manga-ereader-backend — minimal, device-facing API for the KOReader plugin.

Serves the same library as the webapp but tuned for an e-ink Kobo:
  * page images are decoded from any source format (incl. AVIF) and re-encoded
    as downscaled grayscale JPEG, disk-cached so repeat/prefetch hits are cheap;
  * reading progress is written back to the shared manga.db, so the browser
    webapp and the Kobo stay in sync.

It reuses classes/database.py verbatim and mirrors the webapp's CBZ helpers.
"""
import io, json, glob, os, re, sys, zipfile

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from PIL import Image, ImageOps
import pillow_heif

# Register the HEIF/AVIF opener so Pillow can decode AVIF pages (Kobo can't).
pillow_heif.register_heif_opener()

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, '/app')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from classes.database import Database

MANGA_DB = os.environ.get('MANGA_DB', 'manga.db')
MANGA_STORAGE = os.environ.get('MANGA_STORAGE', 'tmp')
THUMBNAILS_DIR = os.environ.get('THUMBNAILS_DIR', 'thumbnails')
LARGE_COVERS_DIR = os.path.join(THUMBNAILS_DIR, '_large')
CACHE_DIR = os.environ.get('EREADER_CACHE', 'ereader_cache')
PORT = int(os.environ.get('PORT', 8080))
DEFAULT_WIDTH = int(os.environ.get('EREADER_DEFAULT_WIDTH', 1072))
JPEG_QUALITY = int(os.environ.get('EREADER_JPEG_QUALITY', 82))

app = FastAPI()


def get_db():
    return Database(MANGA_DB)


# --- helpers mirrored from services/webapp/main.py -------------------------

def thumbnail_path(manga_id):
    return os.path.join(THUMBNAILS_DIR, f'{manga_id}.jpg')


def large_cover_path(manga_id):
    return os.path.join(LARGE_COVERS_DIR, f'{manga_id}.jpg')


def has_thumbnail(manga_id):
    return os.path.exists(thumbnail_path(manga_id))


def extract_chapter_num(filename):
    # Chapter number is the trailing number in the filename (e.g. "Title - 13.5.cbz").
    # Match the END so numbers inside the title (e.g. "...in Her 30s...") are ignored.
    name = filename[:-4] if filename.lower().endswith('.cbz') else filename
    match = re.search(r'(\d+(?:\.\d+)?)\s*$', name)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def list_chapter_files(title):
    if not title:
        return []
    manga_dir = os.path.join(MANGA_STORAGE, title)
    if not os.path.isdir(manga_dir):
        return []
    cbzs = glob.glob(os.path.join(manga_dir, '*.cbz'))
    return sorted([os.path.basename(c) for c in cbzs], key=extract_chapter_num)


def manga_to_payload(row):
    tags = row.get('tags')
    if tags and isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []
    title = row.get('title')
    folder = os.path.join(MANGA_STORAGE, title) if title else None
    return {
        'id': row['id'],
        'url': row['url'],
        'title': title or row['url'],
        'status': row['status'],
        'kobo_sync': row['kobo_sync'],
        'source_type': row['source_type'],
        'cover_url': row.get('cover_url'),
        'has_thumbnail': has_thumbnail(row['id']),
        'author': row.get('author'),
        'demographic': row.get('demographic'),
        'tags': tags or [],
        'description': row.get('description'),
        'english_title': row.get('english_title') or None,
        'japanese_title': row.get('japanese_title') or None,
        'last_downloaded_at': row.get('last_downloaded_at'),
        'last_chapter_on_disk': row.get('last_chapter_on_disk'),
        'favorited': bool(row.get('favorited', 0)),
        'hidden': bool(row.get('hidden', 0)),
        'read': bool(row.get('read', 0)),
        'last_read_chapter': row.get('last_read_chapter'),
        'last_read_page': row.get('last_read_page'),
        'download_enabled': bool(row.get('download_enabled', 0)),
        'alias': row.get('alias') or None,
        'folder_path': folder,
        'folder_exists': bool(folder and os.path.isdir(folder)),
    }


_CBZ_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}


def _cbz_ext(name):
    # Some CBZ files contain entries like "1.jpg_v=12345"; splitext gives the full
    # "_v=..." blob as the extension, so we strip anything after the alpha chars.
    ext = os.path.splitext(name.lower())[1]
    m = re.match(r'(\.[a-z]+)', ext)
    return m.group(1) if m else ext


def _cbz_resolve(manga_id, filename):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga or not manga.get('title'):
        raise HTTPException(status_code=404, detail='Not found')
    safe_name = os.path.basename(filename)
    path = os.path.join(MANGA_STORAGE, manga['title'], safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='File not found')
    return path, safe_name


def _cbz_pages(zf):
    return sorted(n for n in zf.namelist()
                  if _cbz_ext(n) in _CBZ_IMAGE_EXTS
                  and not os.path.basename(n).startswith('.'))


# --- library --------------------------------------------------------------

@app.get('/api/manga')
def list_manga():
    db = get_db()
    return [manga_to_payload(r) for r in db.get_all_manga()]


@app.get('/api/manga/{manga_id}')
def get_manga(manga_id: str):
    db = get_db()
    row = db.get_manga_by_id(manga_id)
    if not row:
        raise HTTPException(status_code=404, detail='Not found')
    payload = manga_to_payload(row)
    payload['chapters'] = list_chapter_files(row.get('title'))
    return payload


@app.get('/api/tags')
def list_tags():
    """Distinct tags across the library with title counts, for tag browsing."""
    db = get_db()
    counts = {}
    for r in db.get_all_manga():
        tags = r.get('tags')
        if tags and isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        for t in (tags or []):
            counts[t] = counts.get(t, 0) + 1
    return [{'tag': t, 'count': c}
            for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))]


class ProgressRequest(BaseModel):
    last_read_chapter: str | None = None
    last_read_page: int | None = None
    read: int | None = None
    favorited: int | None = None
    hidden: int | None = None
    clear_progress: bool | None = None


@app.patch('/api/manga/{manga_id}')
def update_manga(manga_id: str, body: ProgressRequest):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    if body.clear_progress:
        db.clear_reading_progress(manga_id)
    fields = {k: v for k, v in body.dict().items()
              if k != 'clear_progress' and v is not None}
    if fields:
        db.update_manga_metadata(manga_id, manga['url'], **fields)
    return {'ok': True}


# --- chapter pages --------------------------------------------------------

@app.get('/cbz/{manga_id}/{filename}/info')
def cbz_info(manga_id: str, filename: str):
    path, _ = _cbz_resolve(manga_id, filename)
    with zipfile.ZipFile(path) as zf:
        return {'page_count': len(_cbz_pages(zf))}


def _transcode_to_cache(src_bytes, cache_file, width):
    """Decode any source format, downscale to `width`, grayscale, save JPEG."""
    with Image.open(io.BytesIO(src_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert('L')
        if width and img.width > width:
            img.thumbnail((width, width * 8), Image.LANCZOS)
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        tmp = cache_file + '.tmp'
        img.save(tmp, 'JPEG', quality=JPEG_QUALITY, optimize=True)
        os.replace(tmp, cache_file)


@app.get('/cbz/{manga_id}/{filename}/{page_num}')
def cbz_page(manga_id: str, filename: str, page_num: int, w: int = DEFAULT_WIDTH):
    path, safe_name = _cbz_resolve(manga_id, filename)
    width = max(0, min(int(w or 0), 4096))
    cache_file = os.path.join(CACHE_DIR, manga_id, safe_name, f'{page_num}_{width}.jpg')
    if os.path.exists(cache_file):
        return FileResponse(cache_file, media_type='image/jpeg')

    with zipfile.ZipFile(path) as zf:
        pages = _cbz_pages(zf)
        if page_num < 1 or page_num > len(pages):
            raise HTTPException(status_code=404, detail='Page not found')
        data = zf.read(pages[page_num - 1])

    try:
        _transcode_to_cache(data, cache_file, width)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Decode failed: {e}')
    return FileResponse(cache_file, media_type='image/jpeg')


# --- covers ---------------------------------------------------------------

@app.get('/thumbnail/{manga_id}')
def serve_thumbnail(manga_id: str):
    path = thumbnail_path(manga_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='No thumbnail')
    return FileResponse(path, media_type='image/jpeg')


@app.get('/cover/{manga_id}')
def serve_cover(manga_id: str):
    large = large_cover_path(manga_id)
    if os.path.exists(large):
        return FileResponse(large, media_type='image/jpeg')
    thumb = thumbnail_path(manga_id)
    if os.path.exists(thumb):
        return FileResponse(thumb, media_type='image/jpeg')
    raise HTTPException(status_code=404, detail='No cover')


@app.get('/healthz')
def healthz():
    return {'ok': True}


@app.get('/')
def root():
    """Friendly status page — this is a JSON API for the KOReader plugin, not a website."""
    try:
        count = len(get_db().get_all_manga())
    except Exception:
        count = None
    return {
        'service': 'manga-ereader-backend',
        'ok': True,
        'manga_count': count,
        'note': 'JSON API for the KOReader Manga Library plugin. No web UI here — '
                'use the browser webapp for browsing.',
        'endpoints': ['/api/manga', '/api/manga/{id}', '/api/tags',
                      '/cbz/{id}/{filename}/info', '/cbz/{id}/{filename}/{page}?w=',
                      '/thumbnail/{id}', '/cover/{id}', '/healthz'],
    }


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=PORT, reload=False)
