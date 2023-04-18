FROM python:3.9-slim-buster

WORKDIR /app

COPY program.py .

CMD while true; do python program.py; sleep 3600; done

# docker run -v /home/chris/code/manga-kobo/tmp:/app/tmp my-image