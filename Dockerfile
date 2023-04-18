FROM python:3.9-slim-buster

WORKDIR /app

COPY program.py .
COPY requirements.txt .

RUN pip install -r requirements.txt

CMD while true; do python program.py; sleep 3600; done

# docker build -t manga-downloader .
# docker run -v /home/chris/code/manga-kobo/tmp:/app/tmp my-image