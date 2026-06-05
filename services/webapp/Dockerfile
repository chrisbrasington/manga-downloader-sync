FROM python:3.11-slim
WORKDIR /app
COPY services/webapp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY classes/database.py ./classes/database.py
COPY services/webapp/main.py .
COPY services/webapp/static ./static
EXPOSE 8080
CMD ["python", "main.py"]
