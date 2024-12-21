#!/usr/bin/env python3
import argparse

def fix_file_order(filepath):
    """Reorders the lines in the file, moving lines with '1' to the front and '0' at the end."""
    with open(filepath, 'r') as file:
        # Read all lines and strip newlines
        lines = file.readlines()

    # Separate the lines into those with '1' and '0'
    ones = [line for line in lines if ', 1' in line]
    zeros = [line for line in lines if ', 0' in line]

    # Combine them back: ones first, zeros last, maintaining order within each
    sorted_lines = ones + zeros

    # Write the reordered lines back to the file
    with open(filepath, 'w') as file:
        file.writelines(sorted_lines)

    print(f"File '{filepath}' has been reordered.")

def main():
    parser = argparse.ArgumentParser(description="Reorder lines in a file, putting lines with '1' first and '0' at the end.")
    parser.add_argument('-f', '--fix', type=str, required=True, help="Path to the file to fix")
    
    args = parser.parse_args()
    
    fix_file_order(args.fix)

if __name__ == "__main__":
    main()
