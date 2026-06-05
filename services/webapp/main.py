import glob, json, os, re, sys
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
    return {
        'id': row['id'],
        'url': row['url'],
        'title': row.get('title') or row['url'],
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
    }


def fetch_and_save_thumbnail(manga_id, db_path=None):
    db = Database(db_path or MANGA_DB)
    manga = db.get_manga_by_id(manga_id)
    if not manga or manga.get('source_type') != 'mangadex':
        return
    try:
        resp = http_requests.get(
            f'https://api.mangadex.org/cover?manga%5B%5D={manga_id}',
            timeout=10
        )
        data = resp.json().get('data', [])
        if not data:
            return
        filename = data[0]['attributes']['fileName']
        cover_url = f'https://mangadex.org/covers/{manga_id}/{filename}'
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
def api_update_manga(manga_id: str, body: UpdateMangaRequest):
    db = get_db()
    if not db.get_manga_by_id(manga_id):
        raise HTTPException(status_code=404, detail='Not found')
    if body.status is not None:
        if body.status not in ('active', 'completed', 'hiatus'):
            raise HTTPException(status_code=400, detail='Invalid status')
        db.set_manga_status(manga_id, body.status)
    if body.kobo_sync is not None:
        db.set_kobo_sync(manga_id, body.kobo_sync)
    return {'ok': True}


@app.delete('/api/manga/{manga_id}')
def api_remove_manga(manga_id: str):
    db = get_db()
    if not db.get_manga_by_id(manga_id):
        raise HTTPException(status_code=404, detail='Not found')
    db.remove_manga(manga_id)
    return {'ok': True}


@app.post('/api/manga/{manga_id}/fetch-thumbnail')
def api_fetch_thumbnail(manga_id: str, background_tasks: BackgroundTasks):
    db = get_db()
    if not db.get_manga_by_id(manga_id):
        raise HTTPException(status_code=404, detail='Not found')
    background_tasks.add_task(fetch_and_save_thumbnail, manga_id)
    return {'ok': True, 'queued': True}


@app.post('/api/thumbnails/fetch-all')
def api_fetch_all_thumbnails(background_tasks: BackgroundTasks):
    db = get_db()
    rows = [m for m in db.get_all_manga() if m.get('source_type') == 'mangadex' and not has_thumbnail(m['id'])]
    for m in rows:
        background_tasks.add_task(fetch_and_save_thumbnail, m['id'])
    return {'ok': True, 'queued': len(rows)}


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
