#!/usr/bin/env python3
import argparse, os, sys
from classes.parser import Utility 
from classes.source_files import SourceFile

# change sync destination 
device = '/run/media/chris/KOBOeReader'
sync_destination = f'{device}/manga'

def main(args):
    # parsing utility
    util = Utility()

    # if url provided
    if args.url is not None:
        # if adding to sources for future runs
        if args.add:
            util.add_url_to_file(args.url, args.add)

        # process url
        util.process_collection(args.url, sync_destination)
    
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
    
        # if no param run or ongoing
        if len(sys.argv) == 1 or args.ongoing:
            util.process_collection(util.get_collection(args.ongoing), sync_destination)

        # if completed run
        if args.completed:
            util.process_collection(util.get_collection(args.completed), sync_destination)
        
        # if haitus run
        if args.haitus:
            util.process_collection(util.get_collection(args.haitus), sync_destination)

    # print summary 
    util.print_summary()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manga-Kobo downloader and sync', add_help=True)
    parser.add_argument('-u', '--url', help='Url to read from', required=False)
    parser.add_argument('-a', '--add', help='Add url to sources.txt', required=False, nargs='?')
    parser.add_argument('-o', '--ongoing', help='Use ongoing sources.txt', required=False, nargs='?')
    parser.add_argument('-c', '--completed', help='Use completed.txt', required=False, nargs='?')
    parser.add_argument('-d', '--haitus', help='Use dead haitus.txt', required=False, nargs='?')
    parser.add_argument('-f', '--file', help='Convert an existing cbz file to pdf', required=False)
    args = parser.parse_args()

    # this is a bit dumb but I can't tell the difference between
    # and args with None vs its absense
    # so I check for the argv and populate it so that
    #    "if args.ongoing" is easier to discern later
    # plus it's easier to match commands to the files in use anyway
    if '-a' in sys.argv or '--add' in sys.argv:
        args.add = SourceFile.SOURCES.value
    if '-o' in sys.argv or '--ongoing' in sys.argv or len(sys.argv) == 1:
        args.ongoing = SourceFile.SOURCES.value
    if '-c' in sys.argv or '--completed' in sys.argv:
        args.ongoing = SourceFile.COMPLETED.value
    if '-d' in sys.argv or '--haitus' in sys.argv:
        args.ongoing = SourceFile.HIATUS.value
    # -f requires a value

    main(args)