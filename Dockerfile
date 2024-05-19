# Use the official Python 3.9 image as the base image
FROM python:3.9-slim-buster

# Set the working directory to /app
WORKDIR /app

# Copy the program files and requirements.txt file into the container
COPY program.py .
COPY *.py ./
COPY classes/*.py classes/
COPY requirements.txt .
COPY *.txt ./
COPY cache.db ./

# Install the required packages specified in requirements.txt
RUN pip install -r requirements.txt

# Set the command to run the program every 12 hours (3600 1 hour)
# CMD while true; do python program.py; sleep 43200; done
#CMD while true; do
#    python program.py
#    now=$(date +%s)
#    next_run=$(date -d "08:00 next day" +%s)
#    sleep_time=$((next_run - now))
#    sleep_hours=$((sleep_time / 3600))
#    echo "Sleeping for $sleep_hours hours"
#    sleep $sleep_time
#done
CMD ["sh", "-c", "while true; do python program.py; now=$(date +%s); next_run=$(date -d '08:00 next day' +%s); sleep_time=$((next_run - now)); sleep_hours=$((sleep_time / 3600)); echo \"Sleeping for $sleep_hours hours\"; sleep $sleep_time; done"]

# Commands for building, running and managing the container:

# To build the Docker image, run the following command in the same directory as this Dockerfile:
# docker build -t manga-downloader .

# To mount the download folder outside the container, run the following command:
# docker run --name manga-downloader -v /home/chris/code/manga-kobo/tmp:/app/tmp manga-downloader:latest

# To mount the config folder outside the container, run the following command:
# docker run --name manga-downloader -v /home/chris/code/manga-kobo/config:/app/config manga-downloader:latest

# To run the container with an always restart policy, run the following command:
# docker run -e TZ=America/Denver --name manga-downloader -v /home/chris/code/manga-kobo/tmp:/app/tmp --restart always -d manga-downloader:latest

# To view the logs of the container, run the following command:
# docker logs -f manga-downloader
