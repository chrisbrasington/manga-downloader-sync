import os, re, sqlite3, json
from datetime import datetime


class Database:

    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get('MANGA_DB', 'manga.db')
        self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS manga (
                id          TEXT PRIMARY KEY,
                url         TEXT NOT NULL UNIQUE,
                title       TEXT,
                status      TEXT NOT NULL DEFAULT 'active',
                kobo_sync   INTEGER NOT NULL DEFAULT 1,
                source_type TEXT NOT NULL DEFAULT 'mangadex',
                cover_url   TEXT,
                description TEXT,
                author      TEXT,
                demographic TEXT,
                tags        TEXT,
                added_at    TEXT NOT NULL DEFAULT (datetime('now')),
                last_downloaded_at TEXT,
                last_chapter_on_disk REAL
            );

            CREATE TABLE IF NOT EXISTS ignored_chapters (
                chapter_id TEXT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS ignored_scanlations (
                group_id TEXT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS ignore_rename (
                url TEXT PRIMARY KEY
            );

            CREATE INDEX IF NOT EXISTS idx_manga_status ON manga(status);
            CREATE INDEX IF NOT EXISTS idx_manga_kobo_sync ON manga(kobo_sync);
        ''')
        # Add columns introduced after initial schema creation
        for stmt in [
            "ALTER TABLE manga ADD COLUMN favorited INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE manga ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE manga ADD COLUMN read INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE manga ADD COLUMN last_read_chapter TEXT",
            "ALTER TABLE manga ADD COLUMN last_read_page INTEGER",
            "ALTER TABLE manga ADD COLUMN alias TEXT",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        try:
            conn.execute("ALTER TABLE manga ADD COLUMN download_enabled INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists
        # One-time data migration: active manga were the download queue before this field existed.
        # user_version tracks whether this backfill has run so it survives restarts.
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            conn.execute("UPDATE manga SET download_enabled = 1 WHERE status = 'active'")
            conn.execute("PRAGMA user_version = 1")
        conn.commit()
        conn.close()

    def _row_to_dict(self, cursor, row):
        if row is None:
            return None
        return dict(zip([col[0] for col in cursor.description], row))

    # --- manga table ---

    def get_active_manga(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM manga WHERE download_enabled = 1 ORDER BY added_at")
        rows = [self._row_to_dict(c, r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_all_manga(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM manga ORDER BY COALESCE(title, url)")
        rows = [self._row_to_dict(c, r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_manga_by_status(self, status):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM manga WHERE status = ? ORDER BY added_at", (status,))
        rows = [self._row_to_dict(c, r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_manga_by_url(self, url):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM manga WHERE url = ?", (url,))
        row = self._row_to_dict(c, c.fetchone())
        conn.close()
        return row

    def get_manga_by_id(self, manga_id):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM manga WHERE id = ?", (manga_id,))
        row = self._row_to_dict(c, c.fetchone())
        conn.close()
        return row

    def add_manga(self, url, status='active', kobo_sync=1, download_enabled=1):
        manga_id = self._extract_id(url)
        source_type = 'danke' if 'danke.moe' in url else 'mangadex'
        conn = self._connect()
        conn.execute(
            "INSERT OR IGNORE INTO manga (id, url, status, kobo_sync, source_type, download_enabled) VALUES (?, ?, ?, ?, ?, ?)",
            (manga_id, url, status, kobo_sync, source_type, download_enabled)
        )
        conn.commit()
        conn.close()
        return manga_id

    def update_manga_metadata(self, manga_id, url, **kwargs):
        """Upsert: ensure row exists, then update provided metadata fields."""
        allowed = {
            'title', 'cover_url', 'description', 'author', 'demographic', 'tags',
            'last_downloaded_at', 'last_chapter_on_disk', 'status', 'kobo_sync', 'source_type',
            'favorited', 'hidden', 'read', 'last_read_chapter', 'last_read_page', 'download_enabled',
            'alias',
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}

        if 'tags' in updates and isinstance(updates['tags'], list):
            updates['tags'] = json.dumps(updates['tags'])

        conn = self._connect()
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO manga (id, url) VALUES (?, ?)", (manga_id, url))
        if updates:
            set_clause = ', '.join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [manga_id]
            c.execute(f"UPDATE manga SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()

    def clear_reading_progress(self, manga_id):
        conn = self._connect()
        conn.execute("UPDATE manga SET last_read_chapter = NULL, last_read_page = NULL WHERE id = ?", (manga_id,))
        conn.commit()
        conn.close()

    def set_manga_status(self, manga_id, status):
        conn = self._connect()
        conn.execute("UPDATE manga SET status = ? WHERE id = ?", (status, manga_id))
        conn.commit()
        conn.close()

    def set_kobo_sync(self, manga_id, value):
        conn = self._connect()
        conn.execute("UPDATE manga SET kobo_sync = ? WHERE id = ?", (value, manga_id))
        conn.commit()
        conn.close()

    def set_download_enabled(self, manga_id, value):
        conn = self._connect()
        conn.execute("UPDATE manga SET download_enabled = ? WHERE id = ?", (value, manga_id))
        conn.commit()
        conn.close()

    def update_url(self, manga_id, new_url):
        conn = self._connect()
        conn.execute("UPDATE manga SET url = ? WHERE id = ?", (new_url, manga_id))
        conn.commit()
        conn.close()

    def set_alias(self, manga_id, alias):
        conn = self._connect()
        conn.execute("UPDATE manga SET alias = ? WHERE id = ?", (alias, manga_id))
        conn.commit()
        conn.close()

    def remove_manga(self, manga_id):
        conn = self._connect()
        conn.execute("DELETE FROM manga WHERE id = ?", (manga_id,))
        conn.commit()
        conn.close()

    # --- ignored_chapters ---

    def get_ignored_chapters(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT chapter_id FROM ignored_chapters")
        result = {row[0] for row in c.fetchall()}
        conn.close()
        return result

    def add_ignored_chapter(self, chapter_id):
        conn = self._connect()
        conn.execute("INSERT OR IGNORE INTO ignored_chapters (chapter_id) VALUES (?)", (chapter_id,))
        conn.commit()
        conn.close()

    # --- ignored_scanlations ---

    def get_ignored_scanlations(self):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT group_id FROM ignored_scanlations")
        result = {row[0] for row in c.fetchall()}
        conn.close()
        return result

    # --- ignore_rename ---

    def is_rename_ignored(self, url):
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT 1 FROM ignore_rename WHERE url = ?", (url,))
        result = c.fetchone() is not None
        conn.close()
        return result

    def add_rename_ignore(self, url):
        conn = self._connect()
        conn.execute("INSERT OR IGNORE INTO ignore_rename (url) VALUES (?)", (url,))
        conn.commit()
        conn.close()

    # --- helpers ---

    @staticmethod
    def _normalize_title(s):
        """Normalize a title for duplicate detection: lowercase, unify subtitle separators, strip punctuation."""
        s = (s or '').lower().strip()
        s = re.sub(r'\s*[-:–—]\s*', ' ', s)
        s = re.sub(r'[^\w\s]', ' ', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def find_by_normalized_title(self, title):
        """Return all DB entries whose normalized title matches the given title."""
        norm = self._normalize_title(title)
        if not norm:
            return []
        conn = self._connect()
        c = conn.cursor()
        c.execute("SELECT * FROM manga")
        rows = [self._row_to_dict(c, r) for r in c.fetchall()]
        conn.close()
        return [r for r in rows if self._normalize_title(r.get('title') or '') == norm]

    @staticmethod
    def _extract_id(url):
        match = re.search(r'/title/([\w-]+)', url)
        if match:
            return match.group(1)
        # Fallback for non-MangaDex URLs: hash the URL
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()
