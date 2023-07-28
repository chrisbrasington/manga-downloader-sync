#!/usr/bin/env python3
import argparse, os, sys
from classes.parser import Utility 
from classes.source_files import SourceFile
import datetime

# change sync destination 
device = '/run/media/chris/KOBOeReader'
sync_destination = f'{device}/manga'

def main(args):

    current_time = datetime.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    print('Current time: ', current_time)

    # parsing utility
    util = Utility()

    quit_early = False

    # if add url to sources
    if args.add is not None:
        print('adding: ', args.add)
        util.add_url_to_file(args.add, SourceFile.SOURCES.value)
        quit_early = True
    
    # if completed add to completed
    if args.completed is not None:
        print('adding: ', args.completed)
        util.add_url_to_file(args.completed, SourceFile.COMPLETED.value)
        quit_early = True

    # if hiatus add to hiatus
    if args.hiatus is not None:
        print('adding: ', args.hiatus)
        util.add_url_to_file(args.hiatus, SourceFile.HIATUS.value)
        quit_early = True
    
    # quit early if add url
    if quit_early:
        print('Done')
        return

    # if url provided
    if args.url is not None:
        # process url
        util.process_collection(args.url, sync_destination, False)
        return
    
    # if cbz file to convert to pdf
    if args.file is not None:

        if args.file.endswith("cbz"):
            print(f"Converting to pdf: {args.file}")
            util.convert_file_to_pdf(args.file)
        else:
            print("Converting directory to pdf")
            util.convert_dir_to_pdf(args.file)
            print(f'Done: {args.file}')

    else:

        sync_only = args.sync is not None

        if sync_only:
            print('Syncing only')

            if not os.path.exists(sync_destination):
                print(f'Could not find sync destination: {sync_destination}')
                print('Exiting')
                return

        # if completed run
        if args.completed is not None:
            util.process_collection(util.get_collection(args.completed), sync_destination, sync_only)
        
        # if hiatus run
        elif args.hiatus is not None:
            util.process_collection(util.get_collection(args.hiatus), sync_destination, sync_only)
        # if normal run
        else:
            util.process_collection(util.get_collection(SourceFile.SOURCES.value), sync_destination, sync_only)

    # print summary 
    util.print_summary()

    current_time = datetime.datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    print('Done: ', current_time)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manga-Kobo downloader and sync', add_help=True)
    parser.add_argument('-u', '--url', help='Url to read from', required=False, nargs='?')
    parser.add_argument('-a', '--add', help='Add url to sources.txt', required=False, nargs='?')
    parser.add_argument('-c', '--completed', help='Use completed.txt', required=False, nargs='?')
    parser.add_argument('-d', '--hiatus', help='Use dead hiatus.txt', required=False, nargs='?')
    parser.add_argument('-f', '--file', help='Convert an existing cbz file to pdf', required=False)
    parser.add_argument('-s', '--sync', help='Sync only', nargs='?', required=False, const=True)
    args = parser.parse_args()

    # print(args)

    main(args)
