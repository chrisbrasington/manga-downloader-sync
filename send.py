#!/usr/bin/env python3
import argparse
import os, sys
from classes.parser import Utility 
from PIL import Image

syncDestination="/media/chris/KOBOeReader"

def main(args):
    print('~~' * 20)

    # For each folder in args dir sorted
    for folder in sorted(os.listdir(args.dir)):

        # If the folder is a directory
        folder_path = os.path.join(args.dir, folder)

        if os.path.isdir(folder_path):

            # Manga folder is the last folder in args.dir
            manga_folder = os.path.basename(os.path.normpath(args.dir))


            pdf_path = os.path.join(args.dir, f'{manga_folder} - {folder}.pdf')

            # if pdf exists, pass
            if os.path.isfile(pdf_path):
                continue

            print(manga_folder)
            print('~~' * 20)

            # Quote the entire path to handle spaces
            zip_file_path = os.path.join(f'"{args.dir}"', f'"{manga_folder} - {folder}.cbz"')
            print(f'Creating file: {zip_file_path}')

            print(f'From directory: {folder_path}')

            converted_images = []

            # for each image in directory
            for image in sorted(os.listdir(folder_path)):

                # if image is a file
                image_path = os.path.join(folder_path, image)
                if os.path.isfile(image_path):

                    image = Image.open(image_path)
                    converted_images.append(image.convert("L"))

            # save the images as a pdf within this folder_path
            converted_images[0].save(pdf_path, 
                                    save_all=True, 
                                    append_images=converted_images[1:])
            
            # print out new pdf full path
            print(pdf_path)

    pdfs = []

    # for each pdf in args dir sorted
    for pdf in sorted(os.listdir(args.dir)):

        # if pdf is a file
        pdf_path = os.path.join(args.dir, pdf)
        if os.path.isfile(pdf_path):

            # if file ends with .pdf
            if pdf.endswith('.pdf'):

                # add pdf to list
                pdfs.append(pdf_path)

    # for each pdf in list, copy to sync destination / title
    for pdf in pdfs:
        # if pdf exists in destination already, pass
        if os.path.isfile(f'"{syncDestination}/manga/{manga_folder}/{pdf}"'):
            continue
        
        print(f'"{pdf}"')
        # else copy pdf to destination
        os.system(f'cp "{pdf}" "{syncDestination}/manga/{manga_folder}"')

    print(f'Creating Kobo Collection for {manga_folder}')
    util = Utility()
    util.create_kobo_collection(f"{syncDestination}/manga", manga_folder)

    print('\nDone.')

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Convert cbz to pdf')
    parser.add_argument('-d', '--dir', type=str, help='directory to convert')
    args = parser.parse_args()
    main(args)
