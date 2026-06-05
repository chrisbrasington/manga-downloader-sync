import difflib, glob, json, os, re, shutil, sys, time, threading
import requests as http_requests
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, '/app')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from classes.database import Database

MANGA_DB = os.environ.get('MANGA_DB', 'manga.db')
MANGA_STORAGE = os.environ.get('MANGA_STORAGE', 'tmp')
THUMBNAILS_DIR = os.environ.get('THUMBNAILS_DIR', 'thumbnails')
WEBAPP_PORT = int(os.environ.get('WEBAPP_PORT', 8080))

app = FastAPI()
app.mount('/static', StaticFiles(directory='static'), name='static')


@app.on_event('startup')
async def startup():
    threading.Thread(target=_run_scan, daemon=True).start()


def get_db():
    return Database(MANGA_DB)


def thumbnail_path(manga_id):
    return os.path.join(THUMBNAILS_DIR, f'{manga_id}.jpg')


def has_thumbnail(manga_id):
    return os.path.exists(thumbnail_path(manga_id))


def list_chapter_files(title):
    if not title:
        return []
    manga_dir = os.path.join(MANGA_STORAGE, title)
    if not os.path.isdir(manga_dir):
        return []
    pdfs = glob.glob(os.path.join(manga_dir, '*.pdf'))
    return sorted([os.path.basename(p) for p in pdfs])


def extract_chapter_num(filename):
    match = re.search(r'[\s\-]+(\d+(?:\.\d+)?)', filename)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


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
        'last_downloaded_at': row.get('last_downloaded_at'),
        'last_chapter_on_disk': row.get('last_chapter_on_disk'),
        'favorited': bool(row.get('favorited', 0)),
        'hidden': bool(row.get('hidden', 0)),
        'read': bool(row.get('read', 0)),
        'folder_path': folder,
        'folder_exists': bool(folder and os.path.isdir(folder)),
    }


def fetch_and_save_thumbnail(manga_id, db_path=None):
    db = Database(db_path or MANGA_DB)
    manga = db.get_manga_by_id(manga_id)
    if not manga or manga.get('source_type') != 'mangadex':
        return
    url = manga.get('url', '')
    if url.startswith('local:'):
        return
    # UUID in the URL may differ from manga_id for entries originally added as 'local'
    md_uuid = Database._extract_id(url)
    if not md_uuid:
        return
    try:
        resp = http_requests.get(
            f'https://api.mangadex.org/cover?manga%5B%5D={md_uuid}',
            timeout=10
        )
        data = resp.json().get('data', [])
        if not data:
            return
        filename = data[0]['attributes']['fileName']
        cover_url = f'https://mangadex.org/covers/{md_uuid}/{filename}'
        thumb_url = f'{cover_url}.256.jpg'

        os.makedirs(THUMBNAILS_DIR, exist_ok=True)
        img_resp = http_requests.get(thumb_url, timeout=15)
        if img_resp.status_code == 200:
            with open(thumbnail_path(manga_id), 'wb') as f:
                f.write(img_resp.content)
            db.update_manga_metadata(manga_id, manga['url'], cover_url=cover_url)
    except Exception as e:
        print(f'thumbnail fetch failed for {manga_id}: {e}')


# --- page routes ---

@app.get('/', response_class=FileResponse)
def index():
    return 'static/index.html'


@app.get('/admin', response_class=FileResponse)
def admin():
    return 'static/admin.html'


# --- API: manga list ---

@app.get('/api/manga')
def api_manga_list():
    db = get_db()
    rows = db.get_all_manga()
    return [manga_to_payload(r) for r in rows]


@app.get('/api/manga/{manga_id}')
def api_manga_detail(manga_id: str):
    db = get_db()
    row = db.get_manga_by_id(manga_id)
    if not row:
        raise HTTPException(status_code=404, detail='Not found')
    payload = manga_to_payload(row)
    title = row.get('title')
    chapters = list_chapter_files(title)
    payload['chapters'] = sorted(chapters, key=extract_chapter_num)
    return payload


@app.get('/api/stats')
def api_stats():
    db = get_db()
    all_manga = db.get_all_manga()
    counts = {'total': len(all_manga), 'active': 0, 'completed': 0, 'hiatus': 0}
    last_download = None
    for m in all_manga:
        s = m.get('status', 'active')
        if s in counts:
            counts[s] += 1
        ld = m.get('last_downloaded_at')
        if ld and (last_download is None or ld > last_download):
            last_download = ld
    counts['last_download'] = last_download
    return counts


# --- API: admin actions ---

class AddMangaRequest(BaseModel):
    url: str
    status: str = 'active'
    kobo_sync: int = 1


class UpdateMangaRequest(BaseModel):
    status: str | None = None
    kobo_sync: int | None = None
    favorited: int | None = None
    url: str | None = None
    hidden: int | None = None
    read: int | None = None


@app.post('/api/manga', status_code=201)
def api_add_manga(body: AddMangaRequest, background_tasks: BackgroundTasks):
    db = get_db()
    if db.get_manga_by_url(body.url):
        raise HTTPException(status_code=409, detail='URL already exists')
    manga_id = db.add_manga(body.url, status=body.status, kobo_sync=body.kobo_sync)
    if 'mangadex' in body.url:
        background_tasks.add_task(fetch_and_save_thumbnail, manga_id)
    return {'id': manga_id, 'url': body.url}


@app.patch('/api/manga/{manga_id}')
def api_update_manga(manga_id: str, body: UpdateMangaRequest, background_tasks: BackgroundTasks):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    if body.status is not None:
        if body.status not in ('active', 'completed', 'hiatus'):
            raise HTTPException(status_code=400, detail='Invalid status')
        db.set_manga_status(manga_id, body.status)
    if body.kobo_sync is not None:
        db.set_kobo_sync(manga_id, body.kobo_sync)
    if body.favorited is not None:
        db.update_manga_metadata(manga_id, manga['url'], favorited=body.favorited)
    if body.hidden is not None:
        db.update_manga_metadata(manga_id, manga['url'], hidden=body.hidden)
    if body.read is not None:
        db.update_manga_metadata(manga_id, manga['url'], read=body.read)
    if body.url is not None:
        if 'mangadex.org' in body.url:
            new_source = 'mangadex'
        elif 'danke.moe' in body.url:
            new_source = 'danke'
        else:
            new_source = 'local'
        db.update_url(manga_id, body.url)
        db.update_manga_metadata(manga_id, body.url, source_type=new_source)
        if new_source == 'mangadex' and not has_thumbnail(manga_id):
            background_tasks.add_task(fetch_and_save_thumbnail, manga_id)
    return {'ok': True}


@app.delete('/api/manga/{manga_id}')
def api_remove_manga(manga_id: str, delete_folder: bool = False):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    deleted_folder = False
    if delete_folder and manga.get('title'):
        real_storage = os.path.realpath(MANGA_STORAGE)
        real_folder = os.path.realpath(os.path.join(MANGA_STORAGE, manga['title']))
        if os.path.dirname(real_folder) == real_storage and os.path.isdir(real_folder):
            shutil.rmtree(real_folder)
            deleted_folder = True
    db.remove_manga(manga_id)
    return {'ok': True, 'deleted_folder': deleted_folder}


@app.post('/api/manga/{manga_id}/fetch-thumbnail')
def api_fetch_thumbnail(manga_id: str, background_tasks: BackgroundTasks):
    db = get_db()
    if not db.get_manga_by_id(manga_id):
        raise HTTPException(status_code=404, detail='Not found')
    background_tasks.add_task(fetch_and_save_thumbnail, manga_id)
    return {'ok': True, 'queued': True}


@app.get('/api/manga/{manga_id}/covers')
def api_manga_covers(manga_id: str):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    url = manga.get('url', '')
    if url.startswith('local:') or manga.get('source_type') != 'mangadex':
        return []
    md_uuid = Database._extract_id(url)
    if not md_uuid:
        return []
    try:
        resp = http_requests.get(
            f'https://api.mangadex.org/cover?limit=100&manga%5B%5D={md_uuid}&order%5BcreatedAt%5D=asc',
            headers={'accept': 'application/json'},
            timeout=10
        )
        data = resp.json().get('data', [])

        def volume_key(c):
            try:
                return float(c['attributes'].get('volume') or 'inf')
            except ValueError:
                return float('inf')

        data.sort(key=volume_key)

        covers = []
        for item in data:
            fname = item['attributes']['fileName']
            rel_manga_id = item['relationships'][0]['id']
            covers.append({
                'id': item['id'],
                'volume': item['attributes'].get('volume'),
                'locale': item['attributes'].get('locale', ''),
                'thumb_url': f'https://mangadex.org/covers/{rel_manga_id}/{fname}.256.jpg',
                'cover_url': f'https://mangadex.org/covers/{rel_manga_id}/{fname}',
            })
        return covers
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


class SelectCoverRequest(BaseModel):
    cover_url: str
    thumb_url: str


@app.post('/api/manga/{manga_id}/cover')
def api_select_cover(manga_id: str, body: SelectCoverRequest):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    resp = http_requests.get(body.thumb_url, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail='Failed to download cover image')
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    with open(thumbnail_path(manga_id), 'wb') as f:
        f.write(resp.content)
    db.update_manga_metadata(manga_id, manga['url'], cover_url=body.cover_url)
    return {'ok': True}


@app.post('/api/thumbnails/fetch-all')
def api_fetch_all_thumbnails(background_tasks: BackgroundTasks):
    db = get_db()
    rows = [m for m in db.get_all_manga() if m.get('source_type') == 'mangadex' and not has_thumbnail(m['id'])]
    for m in rows:
        background_tasks.add_task(fetch_and_save_thumbnail, m['id'])
    return {'ok': True, 'queued': len(rows)}


# --- scan untracked folders ---

_scan_running = False


def _mangadex_search(title):
    """Search MangaDex for a title. Returns (id, url) or (None, None)."""
    try:
        resp = http_requests.get(
            'https://api.mangadex.org/manga',
            params={'title': title, 'limit': 1, 'order[relevance]': 'desc'},
            timeout=10
        )
        data = resp.json().get('data', [])
        if not data:
            return None, None
        mid = data[0]['id']
        return mid, f'https://mangadex.org/title/{mid}'
    except Exception:
        return None, None


def _run_scan():
    global _scan_running
    _scan_running = True
    added = 0
    errors = 0
    needs_thumbnail = []
    try:
        db = Database(MANGA_DB)
        known = db.get_all_manga()
        known_norm_titles = {Database._normalize_title(m.get('title') or ''): m['id'] for m in known}
        known_ids = {m['id'] for m in known}

        if not os.path.isdir(MANGA_STORAGE):
            print(f'Scan: MANGA_STORAGE not found: {MANGA_STORAGE}')
            return

        folders = sorted(
            f for f in os.listdir(MANGA_STORAGE)
            if os.path.isdir(os.path.join(MANGA_STORAGE, f))
            and Database._normalize_title(f) not in known_norm_titles
        )
        print(f'Scan: {len(folders)} untracked folders to process')

        for folder in folders:
            try:
                # Secondary title check in case known_norm_titles was updated mid-scan
                norm_folder = Database._normalize_title(folder)
                if norm_folder in known_norm_titles:
                    print(f'Scan: skipping "{folder}" — matches existing entry by normalized title')
                    continue

                manga_id, url = _mangadex_search(folder)
                time.sleep(0.35)

                if manga_id and manga_id in known_ids:
                    db.update_manga_metadata(manga_id, url, title=folder)
                    known_norm_titles[norm_folder] = manga_id
                    continue

                if not manga_id:
                    manga_id = Database._extract_id(folder)
                    url = f'local:{folder}'

                db.update_manga_metadata(
                    manga_id, url,
                    title=folder, status='archived', kobo_sync=0,
                    source_type='mangadex' if not url.startswith('local:') else 'local',
                )
                known_norm_titles[norm_folder] = manga_id
                known_ids.add(manga_id)
                added += 1

                if not url.startswith('local:'):
                    needs_thumbnail.append(manga_id)

            except Exception as e:
                errors += 1
                print(f'Scan: error on {folder!r}: {e}')

        print(f'Scan complete: {added} added, {errors} errors')
    finally:
        _scan_running = False

    # Fetch thumbnails after scan is marked done so the flag doesn't stay True during slow network calls
    for manga_id in needs_thumbnail:
        try:
            fetch_and_save_thumbnail(manga_id)
        except Exception as e:
            print(f'Scan: thumbnail error for {manga_id}: {e}')


@app.get('/api/search')
def api_search(title: str):
    manga_id, url = _mangadex_search(title)
    if not manga_id:
        raise HTTPException(status_code=404, detail='Not found on MangaDex')
    return {'id': manga_id, 'url': url}


@app.post('/api/scan')
def api_scan(background_tasks: BackgroundTasks):
    global _scan_running
    if _scan_running:
        return {'ok': False, 'message': 'Scan already in progress'}
    background_tasks.add_task(_run_scan)
    return {'ok': True, 'started': True}


@app.get('/api/scan/status')
def api_scan_status():
    return {'running': _scan_running}


# --- dedupe ---

def _normalize_title(s):
    return Database._normalize_title(s)


def _title_similarity(a, b):
    a = _normalize_title(a)
    b = _normalize_title(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


@app.get('/api/dedupe')
def api_dedupe():
    db = get_db()
    all_manga = db.get_all_manga()
    duplicates = []
    n = len(all_manga)
    for i in range(n):
        for j in range(i + 1, n):
            m1, m2 = all_manga[i], all_manga[j]
            t1 = m1.get('title') or ''
            t2 = m2.get('title') or ''
            if not t1 or not t2:
                continue
            ratio = _title_similarity(t1, t2)
            if ratio < 0.85:
                continue
            c1 = len(list_chapter_files(t1))
            c2 = len(list_chapter_files(t2))
            # Keep: more chapters; tie → prefer mangadex over local
            if c1 > c2 or (c1 == c2 and m1.get('source_type') == 'mangadex'):
                keep, drop, ck, cd = m1, m2, c1, c2
            else:
                keep, drop, ck, cd = m2, m1, c2, c1
            drop_title = drop.get('title') or ''
            keep_title = keep.get('title') or ''
            drop_folder = os.path.join(MANGA_STORAGE, drop_title) if drop_title else None
            keep_folder = os.path.join(MANGA_STORAGE, keep_title) if keep_title else None
            duplicates.append({
                'similarity': round(ratio * 100),
                'keep': {
                    'id': keep['id'], 'title': keep_title, 'url': keep['url'],
                    'source_type': keep.get('source_type'), 'status': keep['status'],
                    'chapter_count': ck, 'folder_path': keep_folder,
                    'folder_exists': bool(keep_title and os.path.isdir(keep_folder)),
                },
                'drop': {
                    'id': drop['id'], 'title': drop_title, 'url': drop['url'],
                    'source_type': drop.get('source_type'), 'status': drop['status'],
                    'chapter_count': cd, 'folder_path': drop_folder,
                    'folder_exists': bool(drop_title and os.path.isdir(drop_folder)),
                },
            })
    return sorted(duplicates, key=lambda x: -x['similarity'])


class DedupeResolveRequest(BaseModel):
    delete_id: str
    delete_folder: str | None = None


@app.post('/api/dedupe/resolve')
def api_dedupe_resolve(body: DedupeResolveRequest):
    db = get_db()
    if not db.get_manga_by_id(body.delete_id):
        raise HTTPException(status_code=404, detail='Manga not found')
    deleted_folder = False
    if body.delete_folder:
        real_storage = os.path.realpath(MANGA_STORAGE)
        real_folder = os.path.realpath(body.delete_folder)
        # Only allow deleting direct children of MANGA_STORAGE — no traversal
        if os.path.dirname(real_folder) != real_storage:
            raise HTTPException(status_code=400, detail='Folder not directly inside storage root')
        if os.path.isdir(real_folder):
            shutil.rmtree(real_folder)
            deleted_folder = True
    db.remove_manga(body.delete_id)
    return {'ok': True, 'deleted_folder': deleted_folder}


# --- file routes ---

@app.get('/thumbnail/{manga_id}')
def serve_thumbnail(manga_id: str):
    path = thumbnail_path(manga_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='No thumbnail')
    return FileResponse(path, media_type='image/jpeg')


@app.get('/pdf/{manga_id}/{filename}')
def serve_pdf(manga_id: str, filename: str, dl: int = 0):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga or not manga.get('title'):
        raise HTTPException(status_code=404, detail='Not found')
    safe_name = os.path.basename(filename)
    path = os.path.join(MANGA_STORAGE, manga['title'], safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='File not found')
    disposition = 'attachment' if dl else 'inline'
    return FileResponse(path, media_type='application/pdf',
                        headers={'Content-Disposition': f'{disposition}; filename="{safe_name}"'})


@app.get('/read/{manga_id}/{filename}', response_class=HTMLResponse)
def read_chapter(manga_id: str, filename: str):
    safe_name = os.path.basename(filename)
    pdf_url = f'/pdf/{manga_id}/{safe_name}'
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{safe_name}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#111; height:100vh; display:flex; flex-direction:column; }}
    .bar {{ background:#1a1a2e; padding:8px 16px; display:flex; align-items:center; gap:12px; }}
    .bar a {{ color:#e2b96f; text-decoration:none; font-size:14px; }}
    .bar span {{ color:#888; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
    iframe {{ flex:1; border:none; width:100%; }}
  </style>
</head>
<body>
  <div class="bar">
    <a href="javascript:history.back()">← Back</a>
    <span>{safe_name}</span>
    <a href="{pdf_url}?dl=1" style="margin-left:auto">↓ Download</a>
  </div>
  <iframe src="{pdf_url}"></iframe>
</body>
</html>'''


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=WEBAPP_PORT, reload=False)
