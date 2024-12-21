# fix.py

def sync_urls():
    # Read URLs from sources.txt and sync.txt
    with open('config/sources.txt', 'r') as f_sources:
        sources = [line.strip() for line in f_sources.readlines()]
    
    with open('config/sync.txt', 'r') as f_sync:
        sync = set(line.strip() for line in f_sync.readlines())  # Using a set for faster lookup
    
    # Create fix.txt with the correct 1 or 0
    with open('config/fix.txt', 'w') as f_fix:
        for url in sources:
            if url in sync:
                f_fix.write(f"{url}, 1\n")
            else:
                f_fix.write(f"{url}, 0\n")

if __name__ == '__main__':
    sync_urls()

