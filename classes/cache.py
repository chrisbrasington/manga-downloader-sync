import os, sqlite3

class MangaData:
    def __init__(self, exists=False, title='', id='', url = ''):
        self.exists = exists
        self.title = title
        self.id = id
        self.url = url

class Cache:
    def manga_exists(self, url):
        self.create_db()
    
        # Connect to SQLite database
        conn = sqlite3.connect('cache.db')
        c = conn.cursor()
        
        # Retrieve the row with the specified ID
        c.execute("SELECT title, id FROM manga WHERE url = ?", (url,))
        row = c.fetchone()
        
        # Close the connection
        conn.close()
        
        if row is None:
            # No row with the specified ID exists
            return MangaData(False, '', '', url)
        else:
            # A row with the specified ID exists
            return MangaData(True, row[0], row[1], url)

    def print_manga_data(self):
        # Connect to SQLite database
        conn = sqlite3.connect('cache.db')
        c = conn.cursor()
        
        # Retrieve all data from the "manga" table
        c.execute("SELECT * FROM manga")
        rows = c.fetchall()
        
        # Print the data
        for row in rows:
            print(row)
        
        # Close the connection
        conn.close()

    def store_manga_data(self, manga_title, manga_id, manga_url):
        self.create_db()

        # Connect to SQLite database
        conn = sqlite3.connect('cache.db')
        c = conn.cursor()
        
        # Check if row already exists
        c.execute("SELECT * FROM manga WHERE id=?", (manga_id,))
        row = c.fetchone()
        if row:
            # print("\nRow already exists with id", manga_id)
            return
        
        # If row doesn't exist, insert data into table
        c.execute("INSERT INTO manga (title, id, url) VALUES (?, ?, ?)", 
                (manga_title, manga_id, manga_url))
        
        # Commit changes and close connection
        conn.commit()
        conn.close()
        # print("Data stored successfully")

    def create_db(self):
        # Check if database file exists, create it and table if not
        if not os.path.exists('cache.db'):
            conn = sqlite3.connect('cache.db')
            c = conn.cursor()
            c.execute('''CREATE TABLE manga
                        (title text, id text, url text, PRIMARY KEY (id))''')
            conn.commit()
            conn.close()
            print("\n Cache Database and table created successfully")
