import asyncio, difflib, glob, http.client, json, os, re, shutil, socket, struct, sys, time, threading, zipfile
import requests as http_requests
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
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
LARGE_COVERS_DIR = os.path.join(THUMBNAILS_DIR, '_large')
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


def large_cover_path(manga_id):
    return os.path.join(LARGE_COVERS_DIR, f'{manga_id}.jpg')


def has_thumbnail(manga_id):
    return os.path.exists(thumbnail_path(manga_id))


def list_chapter_files(title):
    if not title:
        return []
    manga_dir = os.path.join(MANGA_STORAGE, title)
    if not os.path.isdir(manga_dir):
        return []
    cbzs = glob.glob(os.path.join(manga_dir, '*.cbz'))
    return sorted([os.path.basename(c) for c in cbzs])


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
        'download_enabled': bool(row.get('download_enabled', 0)),
        'alias': row.get('alias') or None,
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
    clear_progress: bool | None = None
    alias: str | None = None
    last_chapter_on_disk: float | None = None


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
    if body.clear_progress:
        db.clear_reading_progress(manga_id)
    if body.last_read_chapter is not None:
        db.update_manga_metadata(manga_id, manga['url'], last_read_chapter=body.last_read_chapter)
    if body.last_read_page is not None:
        db.update_manga_metadata(manga_id, manga['url'], last_read_page=body.last_read_page)
    if body.alias is not None:
        db.set_alias(manga_id, body.alias.strip() or None)
    if body.last_chapter_on_disk is not None:
        db.update_manga_metadata(manga_id, manga['url'], last_chapter_on_disk=body.last_chapter_on_disk)
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


@app.get('/api/manga/{manga_id}/titles')
def api_manga_titles(manga_id: str):
    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if not manga:
        raise HTTPException(status_code=404, detail='Not found')
    url = manga.get('url', '')
    if manga.get('source_type') != 'mangadex' or url.startswith('local:'):
        return []
    md_uuid = Database._extract_id(url)
    if not md_uuid:
        return []
    try:
        resp = http_requests.get(
            f'https://api.mangadex.org/manga/{md_uuid}',
            headers={'accept': 'application/json'},
            timeout=10
        )
        data = resp.json().get('data', {})
        attrs = data.get('attributes', {})
        titles = []
        seen = set()
        for locale, t in (attrs.get('title') or {}).items():
            if t and t not in seen:
                titles.append({'title': t, 'locale': locale})
                seen.add(t)
        for alt in (attrs.get('altTitles') or []):
            for locale, t in alt.items():
                if t and t not in seen:
                    titles.append({'title': t, 'locale': locale})
                    seen.add(t)

        def locale_rank(x):
            l = x['locale']
            if l.startswith('en'):
                return 0
            if l.startswith('ja'):
                return 1
            return 2

        titles.sort(key=locale_rank)
        return titles
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
        resp = http_requests.get(body.cover_url + '.256.jpg', timeout=15)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail='Failed to download cover')
        with open(thumbnail_path(manga_id), 'wb') as f:
            f.write(resp.content)
    # Refresh the large cover cache
    large = large_cover_path(manga_id)
    if os.path.exists(large):
        os.remove(large)
    try:
        resp512 = http_requests.get(body.cover_url + '.512.jpg', timeout=15)
        if resp512.status_code == 200:
            os.makedirs(LARGE_COVERS_DIR, exist_ok=True)
            with open(large, 'wb') as f:
                f.write(resp512.content)
    except Exception:
        pass
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
            # Keep: more chapters; tie → prefer download_enabled; tie → prefer mangadex
            if c1 > c2:
                keep, drop, ck, cd = m1, m2, c1, c2
            elif c2 > c1:
                keep, drop, ck, cd = m2, m1, c2, c1
            elif m1.get('download_enabled') and not m2.get('download_enabled'):
                keep, drop, ck, cd = m1, m2, c1, c2
            elif m2.get('download_enabled') and not m1.get('download_enabled'):
                keep, drop, ck, cd = m2, m1, c2, c1
            elif m1.get('source_type') == 'mangadex':
                keep, drop, ck, cd = m1, m2, c1, c2
            else:
                keep, drop, ck, cd = m2, m1, c2, c1
            drop_title = drop.get('title') or ''
            keep_title = keep.get('title') or ''
            drop_folder = os.path.join(MANGA_STORAGE, drop_title) if drop_title else None
            keep_folder = os.path.join(MANGA_STORAGE, keep_title) if keep_title else None
            same_folder = bool(keep_title and drop_title and keep_title == drop_title)
            duplicates.append({
                'similarity': round(ratio * 100),
                'same_folder': same_folder,
                'keep': {
                    'id': keep['id'], 'title': keep_title, 'url': keep['url'],
                    'source_type': keep.get('source_type'), 'status': keep['status'],
                    'chapter_count': ck, 'folder_path': keep_folder,
                    'folder_exists': bool(keep_title and os.path.isdir(keep_folder)),
                    'kobo_sync': keep.get('kobo_sync', 1),
                    'download_enabled': keep.get('download_enabled', 0),
                    'last_chapter_on_disk': keep.get('last_chapter_on_disk'),
                },
                'drop': {
                    'id': drop['id'], 'title': drop_title, 'url': drop['url'],
                    'source_type': drop.get('source_type'), 'status': drop['status'],
                    'chapter_count': cd, 'folder_path': drop_folder,
                    'folder_exists': bool(drop_title and os.path.isdir(drop_folder)),
                    'kobo_sync': drop.get('kobo_sync', 1),
                    'download_enabled': drop.get('download_enabled', 0),
                    'last_chapter_on_disk': drop.get('last_chapter_on_disk'),
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
        folder_title = os.path.basename(real_folder)
        # Don't delete if another DB entry still references this folder
        other = [m for m in db.get_all_manga()
                 if m['id'] != body.delete_id and m.get('title') == folder_title]
        if not other and os.path.isdir(real_folder):
            shutil.rmtree(real_folder)
            deleted_folder = True
    db.remove_manga(body.delete_id)
    return {'ok': True, 'deleted_folder': deleted_folder}


class DedupeMergeRequest(BaseModel):
    keep_id: str
    drop_id: str
    title: str
    kobo_sync: int
    download_enabled: int


@app.post('/api/dedupe/merge')
def api_dedupe_merge(body: DedupeMergeRequest):
    db = get_db()
    keep = db.get_manga_by_id(body.keep_id)
    drop = db.get_manga_by_id(body.drop_id)
    if not keep:
        raise HTTPException(status_code=404, detail='Keep entry not found')
    if not drop:
        raise HTTPException(status_code=404, detail='Drop entry not found')
    if not body.title or '/' in body.title or body.title.startswith('.'):
        raise HTTPException(status_code=400, detail='Invalid title')

    # Rename folder on disk if title changed
    old_title = keep.get('title') or ''
    renamed = False
    if old_title and body.title != old_title:
        old_folder = os.path.join(MANGA_STORAGE, old_title)
        new_folder = os.path.join(MANGA_STORAGE, body.title)
        real_storage = os.path.realpath(MANGA_STORAGE)
        if os.path.dirname(os.path.realpath(new_folder)) != real_storage:
            raise HTTPException(status_code=400, detail='Title would escape storage root')
        if os.path.isdir(old_folder):
            if os.path.exists(new_folder):
                raise HTTPException(status_code=409, detail='A folder with that title already exists')
            os.rename(old_folder, new_folder)
            renamed = True

    # Pick highest last_chapter_on_disk
    k_ch = keep.get('last_chapter_on_disk') or 0
    d_ch = drop.get('last_chapter_on_disk') or 0
    best_chapter = max(k_ch, d_ch)

    update_kwargs = dict(title=body.title, kobo_sync=body.kobo_sync, download_enabled=body.download_enabled)
    if best_chapter:
        update_kwargs['last_chapter_on_disk'] = best_chapter
    db.update_manga_metadata(body.keep_id, keep['url'], **update_kwargs)
    db.remove_manga(body.drop_id)
    return {'ok': True, 'renamed': renamed}


# --- downloader container control ---

DOCKER_SOCKET = '/var/run/docker.sock'
DOWNLOADER_CONTAINER = 'manga'


class _UnixConn(http.client.HTTPConnection):
    def __init__(self):
        super().__init__('localhost')

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(DOCKER_SOCKET)


def _docker(method, path, timeout=15):
    conn = _UnixConn()
    conn.timeout = timeout
    conn.request(method, path, headers={'Host': 'localhost'})
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, body


def _parse_docker_logs(raw):
    """Strip Docker multiplexed-stream headers (8-byte per frame) → plain text."""
    out = []
    i = 0
    while i + 8 <= len(raw):
        size = struct.unpack('>I', raw[i + 4:i + 8])[0]
        chunk = raw[i + 8:i + 8 + size].decode('utf-8', errors='replace')
        out.append(chunk)
        i += 8 + size
    return ''.join(out)


@app.post('/api/downloader/restart')
def api_downloader_restart():
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail='Docker socket not available')
    try:
        status, body = _docker('POST', f'/containers/{DOWNLOADER_CONTAINER}/restart?t=5')
        if status in (204, 200):
            return {'ok': True}
        raise HTTPException(status_code=500, detail=body.decode(errors='replace'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/downloader/logs')
def api_downloader_logs(tail: int = 300):
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail='Docker socket not available')
    try:
        status, body = _docker(
            'GET',
            f'/containers/{DOWNLOADER_CONTAINER}/logs?stdout=1&stderr=1&tail={tail}&timestamps=1',
            timeout=20,
        )
        if status != 200:
            raise HTTPException(status_code=500, detail=body.decode(errors='replace'))
        return {'ok': True, 'logs': _parse_docker_logs(body)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/downloader/logs/stream')
async def api_downloader_logs_stream():
    if not os.path.exists(DOCKER_SOCKET):
        raise HTTPException(status_code=503, detail='Docker socket not available')

    async def generate():
        loop = asyncio.get_running_loop()
        conn = None
        try:
            conn = _UnixConn()
            conn.timeout = 60
            conn.request('GET',
                f'/containers/{DOWNLOADER_CONTAINER}/logs?stdout=1&stderr=1&follow=1&tail=100&timestamps=1',
                headers={'Host': 'localhost'})
            r = conn.getresponse()
            if r.status != 200:
                yield f'data: [error: HTTP {r.status}]\n\n'
                return
            frame_buf = b''
            while True:
                chunk = await loop.run_in_executor(None, r.read, 4096)
                if not chunk:
                    break
                frame_buf += chunk
                while len(frame_buf) >= 8:
                    size = struct.unpack('>I', frame_buf[4:8])[0]
                    if len(frame_buf) < 8 + size:
                        break
                    text = frame_buf[8:8 + size].decode('utf-8', errors='replace')
                    frame_buf = frame_buf[8 + size:]
                    for line in text.splitlines():
                        if line.strip():
                            yield f'data: {line}\n\n'
        except GeneratorExit:
            pass
        except Exception as e:
            try:
                yield f'data: [stream error: {e}]\n\n'
            except Exception:
                pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    return StreamingResponse(
        generate(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# --- file routes ---

@app.get('/thumbnail/{manga_id}')
def serve_thumbnail(manga_id: str):
    path = thumbnail_path(manga_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail='No thumbnail')
    return FileResponse(path, media_type='image/jpeg')


@app.get('/cover/{manga_id}')
def serve_cover(manga_id: str):
    """Serve a 512px cover, downloading and caching it on first access."""
    large = large_cover_path(manga_id)
    if os.path.exists(large):
        return FileResponse(large, media_type='image/jpeg')

    db = get_db()
    manga = db.get_manga_by_id(manga_id)
    if manga and manga.get('cover_url'):
        try:
            resp = http_requests.get(manga['cover_url'] + '.512.jpg', timeout=15)
            if resp.status_code == 200:
                os.makedirs(LARGE_COVERS_DIR, exist_ok=True)
                with open(large, 'wb') as f:
                    f.write(resp.content)
                return FileResponse(large, media_type='image/jpeg')
        except Exception:
            pass

    # Fall back to the small thumbnail
    thumb = thumbnail_path(manga_id)
    if os.path.exists(thumb):
        return FileResponse(thumb, media_type='image/jpeg')

    raise HTTPException(status_code=404, detail='No cover')


_CBZ_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
_CBZ_MEDIA_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.webp': 'image/webp', '.gif': 'image/gif', '.avif': 'image/avif'}

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


@app.get('/cbz/{manga_id}/{filename}/info')
def cbz_info(manga_id: str, filename: str):
    path, _ = _cbz_resolve(manga_id, filename)
    with zipfile.ZipFile(path) as zf:
        pages = sorted(n for n in zf.namelist()
                       if _cbz_ext(n) in _CBZ_IMAGE_EXTS
                       and not os.path.basename(n).startswith('.'))
    return {'page_count': len(pages)}


@app.get('/cbz/{manga_id}/{filename}/{page_num}')
def cbz_page(manga_id: str, filename: str, page_num: int):
    path, _ = _cbz_resolve(manga_id, filename)
    with zipfile.ZipFile(path) as zf:
        pages = sorted(n for n in zf.namelist()
                       if _cbz_ext(n) in _CBZ_IMAGE_EXTS
                       and not os.path.basename(n).startswith('.'))
        if page_num < 1 or page_num > len(pages):
            raise HTTPException(status_code=404, detail='Page not found')
        data = zf.read(pages[page_num - 1])
    ext = _cbz_ext(pages[page_num - 1])
    return Response(content=data, media_type=_CBZ_MEDIA_TYPES.get(ext, 'image/jpeg'))


@app.get('/cbz/{manga_id}/{filename}')
def serve_cbz(manga_id: str, filename: str, dl: int = 0):
    path, safe_name = _cbz_resolve(manga_id, filename)
    disposition = 'attachment' if dl else 'inline'
    return FileResponse(path, media_type='application/zip',
                        headers={'Content-Disposition': f'{disposition}; filename="{safe_name}"'})


@app.get('/read/{manga_id}/{filename}', response_class=HTMLResponse)
def read_chapter(manga_id: str, filename: str):
    safe_name = os.path.basename(filename)
    cbz_url = f'/cbz/{manga_id}/{safe_name}'
    display_name = safe_name[:-4] if safe_name.endswith('.cbz') else safe_name
    manga_id_js = json.dumps(manga_id)
    filename_js = json.dumps(safe_name)
    cbz_url_js = json.dumps(cbz_url)
    display_name_js = json.dumps(display_name)
    return f'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{display_name}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ background:#111; height:100vh; display:flex; flex-direction:column; overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
    .bar {{ background:#1a1a2e; padding:8px 14px; display:flex; align-items:center; gap:10px; flex-shrink:0; min-width:0; }}
    body.fs .bar {{ display:none; }}
    .bar a, .bar button {{ color:#e2b96f; text-decoration:none; font-size:13px; white-space:nowrap; background:none; border:none; cursor:pointer; padding:0; font-family:inherit; }}
    .bar a:hover, .bar button:hover {{ color:#fff; }}
    .bar a.disabled {{ color:#555; pointer-events:none; }}
    .bar .ch-title {{ color:#888; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; text-align:center; min-width:0; }}
    #viewer {{ flex:1; overflow:hidden; display:flex; align-items:center; justify-content:center; position:relative; background:#111; }}
    #page-img {{ max-width:100%; max-height:100%; object-fit:contain; display:none; touch-action:none; }}
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
    @media (max-width:768px) {{
      .bar {{ padding:0 4px; gap:0; min-height:64px; justify-content:space-between; }}
      .bar-m-hide {{ display:none; }}
      .bar a, .bar button {{ font-size:36px; padding:12px 24px; }}
      #next-ch-btn {{ font-size:19px; padding:16px 40px; width:80%; text-align:center; }}
      #back-btn-end {{ font-size:16px; }}
    }}
  </style>
</head>
<body>
  <div class="bar">
    <a class="bar-m-hide" href="javascript:history.back()">← Back</a>
    <a id="prev-ch" class="disabled" href="#">‹</a>
    <span class="ch-title bar-m-hide" id="ch-title"></span>
    <a id="next-ch" class="disabled" href="#">›</a>
    <a class="bar-m-hide" href="{cbz_url}?dl=1">↓</a>
    <button id="fs-btn" title="Fullscreen">⛶</button>
  </div>
  <div id="viewer">
    <div id="loading">Loading…</div>
    <img id="page-img" alt="">
    <div class="hit-zone" id="hz-prev"></div>
    <div class="hit-zone" id="hz-next"></div>
    <div class="page-info" id="page-info"></div>
    <div id="end-screen">
      <div class="msg" id="end-msg">End of chapter</div>
      <a id="next-ch-btn" href="#">Continue to next chapter →</a>
      <a id="back-btn-end" href="javascript:history.back()">← Back to library</a>
    </div>
  </div>
  <script>
    const MANGA_ID = {manga_id_js};
    const FILENAME = {filename_js};
    const CBZ_URL = {cbz_url_js};
    const DISPLAY_NAME = {display_name_js};

    let currentPage = 1, totalPages = 0;
    let chapters = [], currentChIdx = -1;
    let saveTimer = null;

    function pageUrl(n) {{
      return `/cbz/${{encodeURIComponent(MANGA_ID)}}/${{encodeURIComponent(FILENAME)}}/${{n}}`;
    }}

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

    function prefetchPage(n) {{
      if (n < 1 || n > totalPages) return;
      new Image().src = pageUrl(n);
    }}

    function renderPage(n) {{
      zReset();
      applyImageSizing();
      const img = document.getElementById('page-img');
      const loading = document.getElementById('loading');
      img.style.display = 'none';
      loading.style.display = 'flex';
      img.onload = () => {{
        loading.style.display = 'none';
        img.style.display = 'block';
        currentPage = n;
        document.getElementById('page-info').textContent = `${{n}} / ${{totalPages}}`;
        document.getElementById('end-screen').classList.remove('show');
        saveProgress(n);
        prefetchPage(n + 1);
      }};
      img.onerror = () => {{
        loading.textContent = 'Failed to load page.';
      }};
      img.src = pageUrl(n);
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
        const info = await fetch(`/cbz/${{encodeURIComponent(MANGA_ID)}}/${{encodeURIComponent(FILENAME)}}/info`).then(r => r.json());
        totalPages = info.page_count;
        const startPage = Math.min(Math.max(parseInt(new URLSearchParams(window.location.search).get('page')) || 1, 1), totalPages);
        renderPage(startPage);
      }} catch(e) {{
        document.getElementById('loading').textContent = 'Failed to load chapter.';
      }}
    }}

    async function markRead() {{
      try {{
        await fetch(`/api/manga/${{encodeURIComponent(MANGA_ID)}}`, {{
          method: 'PATCH',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{read: 1}})
        }});
      }} catch(e) {{}}
    }}

    function fsUrl(href) {{
      if (!document.fullscreenElement || !href || href === '#') return href;
      const url = new URL(href, location.origin);
      url.searchParams.set('fs', '1');
      return url.toString();
    }}

    function goNext() {{
      const endScreen = document.getElementById('end-screen');
      if (endScreen.classList.contains('show')) {{
        const nextBtn = document.getElementById('next-ch-btn');
        if (nextBtn.style.display === 'inline-block') {{
          window.location.href = fsUrl(nextBtn.href);
        }} else {{
          window.location.href = '/';
        }}
        return;
      }}
      if (currentPage < totalPages) {{
        renderPage(currentPage + 1);
      }} else {{
        endScreen.classList.add('show');
        if (chapters.length > 0 && currentChIdx === chapters.length - 1) {{
          markRead();
          document.getElementById('end-msg').textContent = 'End of manga';
          document.getElementById('back-btn-end').href = '/';
        }}
      }}
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
    ['next-ch', 'prev-ch', 'next-ch-btn'].forEach(id => {{
      document.getElementById(id).addEventListener('click', function(e) {{
        if (!document.fullscreenElement || this.classList.contains('disabled') || !this.href || this.href.endsWith('#')) return;
        e.preventDefault();
        window.location.href = fsUrl(this.href);
      }});
    }});
    document.addEventListener('keydown', e => {{
      if (e.key === 'Escape' && !document.fullscreenElement) {{ history.back(); return; }}
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') goNext();
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') goPrev();
      if (e.key === 'f' || e.key === 'F') document.getElementById('fs-btn').click();
      if (e.key === 'r') rotate(-90);
      if (e.key === 'R') rotate(90);
    }});

    // Fullscreen toggle
    const fsBtn = document.getElementById('fs-btn');
    fsBtn.addEventListener('click', () => {{
      if (!document.fullscreenElement) {{
        document.documentElement.requestFullscreen().catch(() => {{}});
      }} else {{
        document.exitFullscreen();
      }}
    }});
    document.addEventListener('fullscreenchange', () => {{
      const inFs = !!document.fullscreenElement;
      document.body.classList.toggle('fs', inFs);
      fsBtn.textContent = inFs ? '⊠' : '⛶';
      fsBtn.title = inFs ? 'Exit fullscreen' : 'Fullscreen';
    }});

    // Rotation — read from URL, persist on change
    const _qp = new URLSearchParams(window.location.search);
    let currentRot = Math.round((parseInt(_qp.get('rotation')) || 0) / 90) * 90 % 360;
    if (_qp.get('fs') === '1') {{
      document.documentElement.requestFullscreen().catch(() => {{}});
    }}

    function applyImageSizing() {{
      if (currentRot === 90 || currentRot === 270) {{
        // swap constraints so rotated image fills viewer correctly
        zImg.style.maxWidth  = zViewer.clientHeight + 'px';
        zImg.style.maxHeight = zViewer.clientWidth  + 'px';
      }} else {{
        zImg.style.maxWidth  = '';
        zImg.style.maxHeight = '';
      }}
    }}

    function rotate(delta) {{
      currentRot = ((currentRot + delta) % 360 + 360) % 360;
      applyImageSizing();
      zReset();
      const p = new URLSearchParams(window.location.search);
      if (currentRot) p.set('rotation', currentRot); else p.delete('rotation');
      history.replaceState(null, '', window.location.pathname + (p.toString() ? '?' + p : ''));
    }}

    // Pinch zoom + single-finger pan
    let zSc = 1, zTx = 0, zTy = 0;
    let zDistStart = 0, zScStart = 1, zTxStart = 0, zTyStart = 0;
    let zMidXStart = 0, zMidYStart = 0;
    let zPanX = 0, zPanY = 0;
    const zViewer = document.getElementById('viewer');
    const zImg = document.getElementById('page-img');

    function zApply() {{
      if (zSc <= 1) {{ zSc = 1; zTx = 0; zTy = 0; }}
      else {{
        const r = zViewer.getBoundingClientRect();
        const mx = (r.width  * (zSc - 1)) / 2;
        const my = (r.height * (zSc - 1)) / 2;
        zTx = Math.max(-mx, Math.min(mx, zTx));
        zTy = Math.max(-my, Math.min(my, zTy));
      }}
      const rot  = currentRot ? `rotate(${{currentRot}}deg)` : '';
      const zoom = zSc > 1   ? `translate(${{zTx}}px,${{zTy}}px) scale(${{zSc}})` : '';
      zImg.style.transform = [rot, zoom].filter(Boolean).join(' ');
    }}

    function zReset() {{ zSc = 1; zTx = 0; zTy = 0; zApply(); }}

    zViewer.addEventListener('touchstart', e => {{
      if (e.touches.length === 2) {{
        const t0 = e.touches[0], t1 = e.touches[1];
        zDistStart = Math.hypot(t0.clientX - t1.clientX, t0.clientY - t1.clientY);
        zScStart = zSc; zTxStart = zTx; zTyStart = zTy;
        zMidXStart = (t0.clientX + t1.clientX) / 2;
        zMidYStart = (t0.clientY + t1.clientY) / 2;
      }} else if (e.touches.length === 1 && zSc > 1) {{
        zPanX = e.touches[0].clientX;
        zPanY = e.touches[0].clientY;
      }}
    }}, {{ passive: true }});

    zViewer.addEventListener('touchmove', e => {{
      if (e.touches.length === 2) {{
        const t0 = e.touches[0], t1 = e.touches[1];
        const d = Math.hypot(t0.clientX - t1.clientX, t0.clientY - t1.clientY);
        zSc = Math.max(1, Math.min(5, zScStart * d / zDistStart));
        zTx = zTxStart + (t0.clientX + t1.clientX) / 2 - zMidXStart;
        zTy = zTyStart + (t0.clientY + t1.clientY) / 2 - zMidYStart;
        zApply();
        e.preventDefault();
      }} else if (e.touches.length === 1 && zSc > 1) {{
        zTx += e.touches[0].clientX - zPanX;
        zTy += e.touches[0].clientY - zPanY;
        zPanX = e.touches[0].clientX;
        zPanY = e.touches[0].clientY;
        zApply();
        e.preventDefault();
      }}
    }}, {{ passive: false }});

    zViewer.addEventListener('touchend', e => {{
      if (e.touches.length === 0 && zSc < 1.05) zReset();
      // Block hit-zone click while zoomed so single-finger pan doesn't flip pages
      if (zSc > 1.05 && e.touches.length === 0) e.preventDefault();
    }}, {{ passive: false }});

    // Swipe right from left edge → exit fullscreen (only when not zoomed)
    let tsX = 0, tsY = 0;
    document.addEventListener('touchstart', e => {{
      tsX = e.touches[0].clientX;
      tsY = e.touches[0].clientY;
    }}, {{ passive: true }});
    document.addEventListener('touchend', e => {{
      const dx = e.changedTouches[0].clientX - tsX;
      const dy = e.changedTouches[0].clientY - tsY;
      if (document.fullscreenElement && zSc <= 1 && tsX < 44 && dx > 60 && Math.abs(dy) < 100) {{
        document.exitFullscreen();
      }}
    }}, {{ passive: true }});

    init();
  </script>
</body>
</html>'''


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='0.0.0.0', port=WEBAPP_PORT, reload=False)
