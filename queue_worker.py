#!/usr/bin/env python3
"""On-demand ("download as you read") queue worker.

Runs continuously in the downloader image (which has classes/parser.py and all the
download deps). The daily program.py handles full-download manga; this worker handles
manga with download_mode='on_demand':

  1. For a newly added on-demand manga (no manifest yet): fetch the MangaDex feed,
     build the per-chapter manifest, and queue its FIRST chapter.
  2. Periodically refresh manifests so newly published chapters become visible
     (they are only downloaded when the reader requests them, never in bulk).
  3. Drain the work queue: download one queued chapter at a time and mark it
     available (or error).

Chapters are enqueued by the API's PATCH /api/manga/{id} progress handler (read-ahead)
and by step 1 above. The worker never bulk-downloads — that is the whole point.
"""
import os, time, traceback

from classes.parser import Utility
from classes.database import Database

POLL_SECONDS = int(os.environ.get('QUEUE_POLL_SECONDS', '30'))
# How often (in poll loops) to re-fetch feeds for existing on-demand manga to pick up
# newly published chapters. Default ~1h at a 30s poll.
MANIFEST_REFRESH_EVERY = int(os.environ.get('QUEUE_MANIFEST_REFRESH_LOOPS', '120'))


def discover_new_manga(util, db):
    """Build manifests for on-demand manga that don't have one yet and queue chapter 1."""
    for m in db.get_on_demand_manga():
        if m.get('source_type') != 'mangadex':
            continue
        if db.manifest_count(m['id']) > 0:
            continue
        try:
            manga = util.get_manga(m['url'])
            if not manga:
                continue
            util.build_manifest(manga)
            first = db.get_first_chapter_number(manga.id)
            if first is not None:
                db.queue_chapter(manga.id, first)
                print(f'[queue-worker] manifest built for "{manga.title}"; queued first chapter {first}', flush=True)
        except Exception as e:
            print(f'[queue-worker] manifest build failed for {m.get("title") or m["id"]}: {e}', flush=True)


def refresh_manifests(util, db):
    """Refresh manifests for existing on-demand manga (no auto-download)."""
    for m in db.get_on_demand_manga():
        if m.get('source_type') != 'mangadex':
            continue
        try:
            manga = util.get_manga(m['url'])
            if manga:
                util.build_manifest(manga)
        except Exception as e:
            print(f'[queue-worker] manifest refresh failed for {m.get("title") or m["id"]}: {e}', flush=True)


def process_one(util, db):
    """Download a single queued chapter. Returns True if a chapter was processed."""
    row = db.get_queued_chapter()
    if not row:
        return False

    manga_id = row['manga_id']
    num = row['chapter_number']
    db.set_chapter_status(manga_id, num, 'downloading')

    m = db.get_manga_by_id(manga_id)
    if not m:
        db.set_chapter_status(manga_id, num, 'error', 'manga row missing')
        return True

    try:
        manga = util.get_manga(m['url'])
        if not manga:
            db.set_chapter_status(manga_id, num, 'error', 'could not load manga from source')
            return True

        chapters = util.get_chapters(manga)

        # Prefer matching the exact chapter id captured in the manifest; fall back to
        # the canonical chapter number if the feed has shifted.
        target = None
        if row.get('chapter_id'):
            target = next((c for c in chapters if c.id == row['chapter_id']), None)
        if target is None:
            for c in chapters:
                try:
                    if util.extract_number(c) == num:
                        target = c
                        break
                except Exception:
                    continue

        if target is None:
            db.set_chapter_status(manga_id, num, 'error', 'chapter not found in feed')
            return True

        # Normalise chapter.chapter (e.g. 12a -> 12.1) so the written filename matches
        # what build_manifest recorded and what the API parses back from the filename.
        util.extract_number(target)

        folder_title = util.resolve_folder_title(manga)
        util.download_single_chapter(manga, target, folder_title)

        # Keep last_chapter_on_disk roughly in sync for the library UI, mirroring the
        # bulk downloader's bookkeeping.
        try:
            last_ch = util.get_latest_chapter_num_on_disk(f"tmp/{folder_title}", folder_title)
        except Exception:
            last_ch = None
        db.update_manga_metadata(manga.id, m['url'], title=manga.title, last_chapter_on_disk=last_ch)

        db.set_chapter_status(manga_id, num, 'available')
        print(f'[queue-worker] downloaded "{manga.title}" chapter {num}', flush=True)
    except Exception as e:
        traceback.print_exc()
        db.set_chapter_status(manga_id, num, 'error', str(e)[:500])

    return True


def main():
    util = Utility()
    db = Database()
    # Recover orphaned downloads: any chapter left 'downloading' is from a previous
    # worker that died mid-download (the queue only re-picks 'queued'), so re-queue them.
    requeued = db.reset_downloading_to_queued()
    if requeued:
        print(f'[queue-worker] re-queued {requeued} orphaned chapter(s) stuck in downloading', flush=True)
    print(f'[queue-worker] started (poll={POLL_SECONDS}s)', flush=True)
    loop = 0
    while True:
        try:
            discover_new_manga(util, db)
            if loop > 0 and loop % MANIFEST_REFRESH_EVERY == 0:
                refresh_manifests(util, db)
            # Drain the queue fully each cycle, one chapter at a time.
            while process_one(util, db):
                pass
        except Exception:
            traceback.print_exc()
        loop += 1
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
