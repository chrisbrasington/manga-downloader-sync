#!/usr/bin/env python3
import argparse, os, datetime
from classes.parser import Utility
from classes.database import Database

device = '/media/chris/KOBOeReader'
sync_destination = f'{device}/manga'
MANGA_STORAGE = os.environ.get('MANGA_STORAGE', 'tmp')


def _write_heartbeat():
    path = os.path.join(MANGA_STORAGE, '.downloader_heartbeat')
    try:
        with open(path, 'w') as f:
            f.write(datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'))
    except Exception as e:
        print(f'Warning: could not write heartbeat: {e}')


def main(args):
    current_time = datetime.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    print('Current time: ', current_time)

    util = Utility()
    db = Database()

    # Single URL download
    if args.url is not None:
        util.process_collection(args.url, sync_destination, False)
        util.print_summary()
        return

    # CBZ-to-PDF conversion
    if args.file is not None:
        if args.file.endswith('cbz'):
            print(f'Converting to pdf: {args.file}')
            util.convert_file_to_pdf(args.file)
        else:
            print('Converting directory to pdf')
            util.convert_dir_to_pdf(args.file)
            print(f'Done: {args.file}')
        return

    sync_only = args.sync is not None

    if sync_only:
        print('Syncing only')
        if not os.path.exists(sync_destination):
            print(f'Could not find sync destination: {sync_destination}')
            print('Exiting')
            return

    _write_heartbeat()
    # On-demand ("download as you read") manga are handled by queue_worker.py, not the
    # daily bulk run — exclude them here so the cron only fully downloads full-mode manga.
    source = db.get_full_download_manga()
    print(f'Found {len(source)} full-download manga in database')

    util.process_collection(source, sync_destination, sync_only)
    util.print_summary()

    current_time = datetime.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    print('Done: ', current_time)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manga-Kobo downloader and sync', add_help=True)
    parser.add_argument('-u', '--url', help='URL to download', required=False, nargs='?')
    parser.add_argument('-f', '--file', help='Convert an existing cbz file or directory to pdf', required=False)
    parser.add_argument('-s', '--sync', help='Sync to Kobo only (skip download)', nargs='?', required=False, const=True)
    args = parser.parse_args()

    main(args)
