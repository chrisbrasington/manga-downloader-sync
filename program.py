#!/usr/bin/env python3
import argparse, os, datetime
from classes.parser import Utility
from classes.database import Database

device = '/media/chris/KOBOeReader'
sync_destination = f'{device}/manga'


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

    source = db.get_active_manga()
    print(f'Found {len(source)} active manga in database')

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
