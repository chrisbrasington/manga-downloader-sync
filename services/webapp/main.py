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
DOWNLOADER_HEARTBEAT = os.path.join(MANGA_STORAGE, '.downloader_heartbeat')
THUMBNAILS_DIR = os.environ.get('THUMBNAILS_DIR', 'thumbnails')
PICKER_CACHE_DIR = os.path.join(THUMBNAILS_DIR, '_picker')
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
        'last_read_chapter': row.get('last_read_chapter'),
        'last_read_page': row.get('last_read_page'),
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
    last_run = None
    if os.path.exists(DOWNLOADER_HEARTBEAT):
        with open(DOWNLOADER_HEARTBEAT) as f:
            last_run = f.read().strip()
    counts['last_run'] = last_run
    return counts


# --- API: admin actions ---

class AddMangaRequest(BaseModel):
    url: str
    status: str = 'active'
    kobo_sync: int = 1
    download_enabled: int = 1


class UpdateMangaRequest(BaseModel):
    status: str | None = None
    kobo_sync: int | None = None
    download_enabled: int | None = None
    favorited: int | None = None
    url: str | None = None
    hidden: int | None = None
    read: int | None = None
    last_read_chapter: str | None = None
    last_read_page: int | None = None


@app.post('/api/manga', status_code=201)
def api_add_manga(body: AddMangaRequest, background_tasks: BackgroundTasks):
    db = get_db()
    if db.get_manga_by_url(body.url):
        raise HTTPException(status_code=409, detail='URL already exists')
    manga_id = db.add_manga(body.url, status=body.status, kobo_sync=body.kobo_sync, download_enabled=body.download_enabled)
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
    if body.download_enabled is not None:
        db.set_download_enabled(manga_id, body.download_enabled)
    if body.favorited is not None:
        db.update_manga_metadata(manga_id, manga['url'], favorited=body.favorited)
    if body.hidden is not None:
        db.update_manga_metadata(manga_id, manga['url'], hidden=body.hidden)
    if body.read is not None:
        db.update_manga_metadata(manga_id, manga['url'], read=body.read)
    if body.last_read_chapter is not None:
        db.update_manga_metadata(manga_id, manga['url'], last_read_chapter=body.last_read_chapter)
    if body.last_read_page is not None:
        db.update_manga_metadata(manga_id, manga['url'], last_read_page=body.last_read_page)
    if body.url is not None:
        existing = db.get_manga_by_url(body.url)
        if existing and existing['id'] != manga_id:
            ex_title = existing.get('title') or existing['id']
            my_title = manga.get('title') or manga_id
            raise HTTPException(
                status_code=409,
                detail={
                    'message': 'URL already in use',
                    'mine': {
                        'id': manga_id,
                        'title': my_title,
                        'chapter_count': len(list_chapter_files(manga.get('title'))),
                        'folder_path': os.path.join(MANGA_STORAGE, manga['title']) if manga.get('title') else None,
                        'folder_exists': bool(manga.get('title') and os.path.isdir(os.path.join(MANGA_STORAGE, manga['title']))),
                    },
                    'conflict': {
                        'id': existing['id'],
                        'title': ex_title,
                        'chapter_count': len(list_chapter_files(existing.get('title'))),
                        'folder_path': os.path.join(MANGA_STORAGE, ex_title) if existing.get('title') else None,
                        'folder_exists': bool(existing.get('title') and os.path.isdir(os.path.join(MANGA_STORAGE, ex_title))),
                    },
                }
            )
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
    # Clear stale picker cache for this manga
    picker_dir = os.path.join(PICKER_CACHE_DIR, manga_id)
    if os.path.isdir(picker_dir):
        shutil.rmtree(picker_dir)
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
                # proxy URL — browser fetches through our server, bypassing MangaDex hotlink protection
                'thumb_url': f'/api/manga/{manga_id}/cover-proxy/{rel_manga_id}/{fname}',
                'cover_url': f'https://mangadex.org/covers/{rel_manga_id}/{fname}',
            })
        return covers
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get('/api/manga/{manga_id}/cover-proxy/{rel_id}/{filename}')
def api_cover_proxy(manga_id: str, rel_id: str, filename: str):
    picker_dir = os.path.join(PICKER_CACHE_DIR, manga_id)
    cache_path = os.path.join(picker_dir, filename)
    if not os.path.exists(cache_path):
        thumb_url = f'https://mangadex.org/covers/{rel_id}/{filename}.256.jpg'
        resp = http_requests.get(thumb_url, timeout=15)
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail='Cover not found')
        os.makedirs(picker_dir, exist_ok=True)
        with open(cache_path, 'wb') as f:
            f.write(resp.content)
    return FileResponse(cache_path, media_type='image/jpeg')


class SelectCoverRequest(BaseModel):
    cover_url: str  # MangaDex full URL — used to find cached file and store in DB


@app.post('/api/manga/{manga_id}/cover')
def api_select_cover(manga_id: str, body: SelectCoverRequest):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    fname = body.cover_url.rsplit('/', 1)[-1]
    cached = os.path.join(PICKER_CACHE_DIR, manga_id, fname)
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)
    if os.path.exists(cached):
        shutil.copy2(cached, thumbnail_path(manga_id))
    else:
        # Cache miss — download directly
        resp = http_requests.get(body.cover_url + '.256.jpg', timeout=15)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail='Failed to download cover')
        with open(thumbnail_path(manga_id), 'wb') as f:
            f.write(resp.content)
    db.update_manga_metadata(manga_id, manga['url'], cover_url=body.cover_url)
    # Clean up picker cache
    picker_dir = os.path.join(PICKER_CACHE_DIR, manga_id)
    if os.path.isdir(picker_dir):
        shutil.rmtree(picker_dir)
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
    display_name = safe_name[:-4] if safe_name.endswith('.pdf') else safe_name
    manga_id_js = json.dumps(manga_id)
    filename_js = json.dumps(safe_name)
    pdf_url_js = json.dumps(pdf_url)
    display_name_js = json.dumps(display_name)
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{display_name}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#111; height:100vh; display:flex; flex-direction:column; overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
    .bar {{ background:#1a1a2e; padding:8px 14px; display:flex; align-items:center; gap:10px; flex-shrink:0; min-width:0; }}
    .bar a {{ color:#e2b96f; text-decoration:none; font-size:13px; white-space:nowrap; }}
    .bar a:hover {{ color:#fff; }}
    .bar a.disabled {{ color:#444; pointer-events:none; }}
    .bar .ch-title {{ color:#888; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; text-align:center; min-width:0; }}
    #viewer {{ flex:1; overflow:hidden; display:flex; align-items:center; justify-content:center; position:relative; background:#111; }}
    #page-canvas {{ display:block; }}
    #page-canvas-over {{ display:none; position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); pointer-events:none; }}
    .hit-zone {{ position:absolute; top:0; bottom:0; width:35%; cursor:pointer; z-index:10; }}
    #hz-prev {{ left:0; }}
    #hz-next {{ right:0; }}
    .page-info {{ position:absolute; bottom:12px; left:50%; transform:translateX(-50%); background:rgba(0,0,0,.55); color:#999; font-size:11px; padding:3px 9px; border-radius:8px; pointer-events:none; transition:opacity .3s; }}
    #end-screen {{ position:absolute; inset:0; background:rgba(0,0,0,.82); display:none; align-items:center; justify-content:center; flex-direction:column; gap:18px; z-index:20; }}
    #end-screen.show {{ display:flex; }}
    #end-screen .msg {{ color:#ccc; font-size:15px; }}
    #next-ch-btn {{ background:#e2b96f; color:#111; border:none; padding:12px 32px; border-radius:6px; font-size:16px; font-weight:600; cursor:pointer; text-decoration:none; display:none; }}
    #next-ch-btn:hover {{ background:#f0cc88; }}
    #back-btn-end {{ color:#888; font-size:13px; text-decoration:none; }}
    #back-btn-end:hover {{ color:#ccc; }}
    #loading {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#555; font-size:14px; }}
    /*#dbg {{ position:absolute; top:8px; right:8px; background:rgba(0,0,0,.75);
            color:#e2b96f; font-size:10px; font-family:monospace; padding:6px 8px;
            border-radius:6px; pointer-events:none; z-index:30; white-space:pre; line-height:1.5; }}*/
    @media (max-width:600px) {{
      .bar {{ padding:10px 14px; gap:14px; }}
      .bar a {{ font-size:17px; padding:4px 2px; }}
      .bar .ch-title {{ font-size:13px; }}
      #next-ch-btn {{ font-size:19px; padding:16px 40px; width:80%; text-align:center; }}
      #back-btn-end {{ font-size:16px; }}
    }}
  </style>
</head>
<body>
  <div class="bar">
    <a href="javascript:history.back()">← Back</a>
    <a id="prev-ch" class="disabled" href="#">‹ Prev</a>
    <span class="ch-title" id="ch-title"></span>
    <a id="next-ch" class="disabled" href="#">Next ›</a>
    <a href="{pdf_url}?dl=1">↓</a>
  </div>
  <div id="viewer">
    <div id="loading">Loading…</div>
    <canvas id="page-canvas" style="display:none"></canvas>
    <canvas id="page-canvas-over"></canvas>
    <div class="hit-zone" id="hz-prev"></div>
    <div class="hit-zone" id="hz-next"></div>
    <div class="page-info" id="page-info"></div>
    <!--<div id="dbg">waiting...</div>-->
    <div id="end-screen">
      <div class="msg" id="end-msg">End of chapter</div>
      <a id="next-ch-btn" href="#">Continue to next chapter →</a>
      <a id="back-btn-end" href="javascript:history.back()">← Back to library</a>
    </div>
  </div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
  <script>
    const MANGA_ID = {manga_id_js};
    const FILENAME = {filename_js};
    const PDF_URL = {pdf_url_js};
    const DISPLAY_NAME = {display_name_js};

    pdfjsLib.GlobalWorkerOptions.workerSrc =
      'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

    let pdfDoc = null, currentPage = 1, totalPages = 0;
    let chapters = [], currentChIdx = -1, rendering = false;
    let saveTimer = null, overTimer = null;
    let pageCache = {{}}, prefetching = new Set();

    function saveProgress(page) {{
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {{
        fetch(`/api/manga/${{encodeURIComponent(MANGA_ID)}}`, {{
          method: 'PATCH',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{last_read_chapter: FILENAME, last_read_page: page}})
        }}).catch(() => {{}});
      }}, 800);
    }}

    function extractNum(f) {{
      const m = f.match(/[\\s\\-]+(\\d+(?:\\.\\d+)?)/);
      return m ? parseFloat(m[1]) : 0;
    }}

    function updateNav() {{
      const prevEl = document.getElementById('prev-ch');
      const nextEl = document.getElementById('next-ch');
      const nextBtn = document.getElementById('next-ch-btn');
      if (currentChIdx > 0) {{
        const u = `/read/${{encodeURIComponent(MANGA_ID)}}/${{encodeURIComponent(chapters[currentChIdx - 1])}}`;
        prevEl.href = u;
        prevEl.classList.remove('disabled');
      }}
      if (currentChIdx >= 0 && currentChIdx < chapters.length - 1) {{
        const u = `/read/${{encodeURIComponent(MANGA_ID)}}/${{encodeURIComponent(chapters[currentChIdx + 1])}}`;
        nextEl.href = u;
        nextEl.classList.remove('disabled');
        nextBtn.href = u;
        nextBtn.style.display = 'inline-block';
      }}
    }}

    async function init() {{
      document.getElementById('ch-title').textContent = DISPLAY_NAME;
      try {{
        const data = await fetch(`/api/manga/${{encodeURIComponent(MANGA_ID)}}`).then(r => r.json());
        chapters = (data.chapters || []).slice().sort((a, b) => extractNum(a) - extractNum(b));
        currentChIdx = chapters.indexOf(FILENAME);
        updateNav();
      }} catch(e) {{}}

      try {{
        pdfDoc = await pdfjsLib.getDocument(PDF_URL).promise;
        totalPages = pdfDoc.numPages;
        document.getElementById('loading').style.display = 'none';
        document.getElementById('page-canvas').style.display = 'block';
        const startPage = Math.min(Math.max(parseInt(new URLSearchParams(window.location.search).get('page')) || 1, 1), totalPages);
        await renderPage(startPage);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load PDF.';
      }}
    }}

    async function renderToCanvas(n) {{
      const page = await pdfDoc.getPage(n);
      const vp0 = page.getViewport({{scale: 1}});
      const viewer = document.getElementById('viewer');
      const screenDpr = window.devicePixelRatio || 1;
      const zoomScale = window.visualViewport ? window.visualViewport.scale : 1;
      const dpr = screenDpr * zoomScale;
      const fitScale = Math.min(viewer.clientHeight / vp0.height, viewer.clientWidth / vp0.width);
      const scale = fitScale * dpr;
      const vp = page.getViewport({{scale}});
      const tmp = document.createElement('canvas');
      tmp.width = Math.round(vp.width);
      tmp.height = Math.round(vp.height);
      await page.render({{canvasContext: tmp.getContext('2d'), viewport: vp}}).promise;
      return {{canvas: tmp, cssW: (tmp.width / dpr) + 'px', cssH: (tmp.height / dpr) + 'px'}};
    }}

    async function prefetchPage(n) {{
      if (!pdfDoc || n < 1 || n > totalPages || pageCache[n] || prefetching.has(n)) return;
      prefetching.add(n);
      try {{ pageCache[n] = await renderToCanvas(n); }} catch(e) {{}}
      prefetching.delete(n);
    }}

    async function renderPage(n, fade) {{
      if (rendering || !pdfDoc) return;
      rendering = true;
      clearTimeout(overTimer);
      const over = document.getElementById('page-canvas-over');
      over.style.display = 'none';
      try {{
        let tmp, cssW, cssH;
        if (pageCache[n]) {{
          ({{canvas: tmp, cssW, cssH}} = pageCache[n]);
          delete pageCache[n];
        }} else {{
          ({{canvas: tmp, cssW, cssH}} = await renderToCanvas(n));
        }}
        const canvas = document.getElementById('page-canvas');
        if (fade) {{
          // Render into overlay; fade it in over the still-visible main canvas
          over.width = tmp.width;
          over.height = tmp.height;
          over.style.width = cssW;
          over.style.height = cssH;
          over.getContext('2d').drawImage(tmp, 0, 0);
          over.style.transition = 'none';
          over.style.opacity = '0';
          over.style.display = 'block';
          void over.offsetWidth;
          over.style.transition = 'opacity 0.25s';
          over.style.opacity = '1';
          // After fade, promote overlay content to main canvas and hide overlay
          overTimer = setTimeout(() => {{
            canvas.width = tmp.width;
            canvas.height = tmp.height;
            canvas.style.width = cssW;
            canvas.style.height = cssH;
            canvas.getContext('2d').drawImage(tmp, 0, 0);
            over.style.transition = 'none';
            over.style.opacity = '0';
            over.style.display = 'none';
          }}, 280);
        }} else {{
          // Synchronous swap — no await between clear and fill, browser sees only final state
          canvas.width = tmp.width;
          canvas.height = tmp.height;
          canvas.style.width = cssW;
          canvas.style.height = cssH;
          canvas.getContext('2d').drawImage(tmp, 0, 0);
        }}
        currentPage = n;
        document.getElementById('page-info').textContent = `${{n}} / ${{totalPages}}`;
        document.getElementById('end-screen').classList.remove('show');
        saveProgress(n);
      }} finally {{
        rendering = false;
        prefetchPage(n + 1);
      }}
    }}

    function goNext() {{
      if (currentPage < totalPages) {{ renderPage(currentPage + 1); }}
      else {{ document.getElementById('end-screen').classList.add('show'); }}
    }}
    function goPrev() {{
      if (document.getElementById('end-screen').classList.contains('show')) {{
        document.getElementById('end-screen').classList.remove('show');
      }} else if (currentPage > 1) {{
        renderPage(currentPage - 1);
      }}
    }}

    document.getElementById('hz-next').addEventListener('click', goNext);
    document.getElementById('hz-prev').addEventListener('click', goPrev);
    document.addEventListener('keydown', e => {{
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') goNext();
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') goPrev();
    }});

    if (window.visualViewport) {{
      let _zt = null;
      window.visualViewport.addEventListener('resize', () => {{
        clearTimeout(_zt);
        pageCache = {{}};
        _zt = setTimeout(() => {{ if (pdfDoc) renderPage(currentPage, true); }}, 350);
      }});
    }}

    init();
  </script>
</body>
</html>'''


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=WEBAPP_PORT, reload=False)
