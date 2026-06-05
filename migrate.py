#!/usr/bin/env python3
"""One-time migration from text config files to manga.db. Safe to run multiple times."""
import os, sqlite3, sys

sys.path.insert(0, os.path.dirname(__file__))
from classes.database import Database


def strip_sync_flag(line):
    """Strip trailing ,0 or ,1 from a URL line. Returns (url, sync_flag)."""
    line = line.strip()
    if line.endswith(',0'):
        return line[:-2], 0
    if line.endswith(',1'):
        return line[:-2], 1
    return line, 1


def migrate_sources(db, path, status):
    if not os.path.exists(path):
        return 0
    count = 0
    conn = sqlite3.connect(db.db_path)
    c = conn.cursor()
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            url, sync_flag = strip_sync_flag(line)
            manga_id = Database._extract_id(url)
            source_type = 'danke' if 'danke.moe' in url else 'mangadex'
            c.execute(
                "INSERT OR IGNORE INTO manga (id, url, status, kobo_sync, source_type) VALUES (?, ?, ?, ?, ?)",
                (manga_id, url, status, sync_flag, source_type)
            )
            if c.rowcount > 0:
                count += 1
    conn.commit()
    conn.close()
    return count


def backfill_titles(db, cache_db_path):
    if not os.path.exists(cache_db_path):
        print(f'  (no {cache_db_path} found, skipping title backfill)')
        return 0
    conn_cache = sqlite3.connect(cache_db_path)
    rows = conn_cache.execute("SELECT title, id, url FROM manga").fetchall()
    conn_cache.close()

    count = 0
    conn = sqlite3.connect(db.db_path)
    for title, manga_id, url in rows:
        r = conn.execute(
            "UPDATE manga SET title = ? WHERE id = ? AND title IS NULL",
            (title, manga_id)
        )
        if r.rowcount > 0:
            count += 1
    conn.commit()
    conn.close()
    return count


def migrate_simple_list(db, path, table, column):
    if not os.path.exists(path):
        return 0
    count = 0
    conn = sqlite3.connect(db.db_path)
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = conn.execute(f"INSERT OR IGNORE INTO {table} ({column}) VALUES (?)", (line,))
            if r.rowcount > 0:
                count += 1
    conn.commit()
    conn.close()
    return count


def migrate_ignore_rename(db, path):
    if not os.path.exists(path):
        return 0
    count = 0
    conn = sqlite3.connect(db.db_path)
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            url, _ = strip_sync_flag(line)
            r = conn.execute("INSERT OR IGNORE INTO ignore_rename (url) VALUES (?)", (url,))
            if r.rowcount > 0:
                count += 1
    conn.commit()
    conn.close()
    return count


def main():
    db_path = os.environ.get('MANGA_DB', 'manga.db')
    print(f'Migrating to: {db_path}')

    db = Database(db_path)
    print('Schema initialized.')

    active = migrate_sources(db, 'config/sources.txt', 'active')
    completed = migrate_sources(db, 'config/completed.txt', 'completed')
    hiatus = migrate_sources(db, 'config/hiatus.txt', 'hiatus')
    print(f'  manga: {active} active, {completed} completed, {hiatus} hiatus')

    titles = backfill_titles(db, 'cache.db')
    print(f'  titles backfilled from cache.db: {titles}')

    chapters = migrate_simple_list(db, 'config/ignore.txt', 'ignored_chapters', 'chapter_id')
    print(f'  ignored_chapters: {chapters}')

    scanlations = migrate_simple_list(db, 'config/ignore_scanlation.txt', 'ignored_scanlations', 'group_id')
    scanlations += migrate_simple_list(db, 'config/ignore_scanlation.txt.back', 'ignored_scanlations', 'group_id')
    print(f'  ignored_scanlations: {scanlations}')

    renames = migrate_ignore_rename(db, 'config/ignore_rename.txt')
    print(f'  ignore_rename: {renames}')

    # Final summary
    conn = sqlite3.connect(db.db_path)
    print('\nFinal row counts:')
    for table in ['manga', 'ignored_chapters', 'ignored_scanlations', 'ignore_rename']:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f'  {table}: {n}')
    conn.close()

    print('\nMigration complete.')


if __name__ == '__main__':
    main()
