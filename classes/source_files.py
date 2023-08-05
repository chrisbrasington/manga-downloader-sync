import enum

class SourceFile(enum.Enum):
    SOURCES = "./config/sources.txt"
    COMPLETED = "./config/completed.txt"
    HIATUS = "./config/hiatus.txt"