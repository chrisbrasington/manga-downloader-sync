FROM python:3.9-slim-buster

WORKDIR /app

COPY program.py .
COPY *.py ./
COPY classes/*.py classes/
COPY requirements.txt .
COPY *.txt ./
COPY cache.db ./

RUN pip install -r requirements.txt

# every 1 hour
CMD while true; do python program.py; sleep 3600; done

# rebuild docker file
# docker build -t manga-downloader .
# mount download folder outside docker
# docker run --name manga-downloader -v /home/chris/code/manga-kobo/tmp:/app/tmp manga-downloader:latest
# mount config folder outside docker
# docker run --name manga-downloader -v /home/chris/code/manga-kobo/config:/app/config manga-downloader:latest
# run with an always restart
# docker run -e TZ=America/Denver --name manga-downloader -v /home/chris/code/manga-kobo/tmp:/app/tmp --restart always -d manga-downloader:latest
# view logs
# docker logs -f manga-downloader
