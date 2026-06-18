FROM python:3.11-slim
WORKDIR /app
# libheif is needed for pillow-heif to decode AVIF pages
RUN apt-get update && apt-get install -y --no-install-recommends libheif1 \
    && rm -rf /var/lib/apt/lists/*
COPY services/ereader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY classes/database.py ./classes/database.py
COPY services/ereader/main.py .
EXPOSE 8080
CMD ["python", "main.py"]
