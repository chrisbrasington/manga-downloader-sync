FROM python:3.9-slim-buster

WORKDIR /app

COPY program.py .
COPY *.py ./
COPY classes/*.py classes/
COPY requirements.txt .
COPY *.txt ./
COPY cache.db ./

RUN pip install -r requirements.txt

CMD while true; do python program.py; sleep 3600; done

# docker build -t manga-downloader .
# docker run --name manga-downloader -v /home/chris/code/manga-kobo/tmp:/app/tmp manga-downloader:latest
# docker run -e TZ=America/Denver --name manga-downloader -v /home/chris/code/manga-kobo/tmp:/app/tmp --restart always -d manga-downloader:latest
# docker logs -f manga-downloader