import enum, os

def is_running_in_docker():
    # Check if the DOCKER_CONTAINER environment variable is set
    return os.environ['PWD'] == '/app'

class SourceFile(enum.Enum):

    if is_running_in_docker(): 
        SOURCES = "/app/config/sources.txt"
        COMPLETED = "/app/config/completed.txt"
        HIATUS = "/app/config/hiatus.txt"
    else:
        SOURCES = "./config/sources.txt"
        COMPLETED = "./config/completed.txt"
        HIATUS = "./config/hiatus.txt"