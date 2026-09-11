# Contract: the app must listen on $PORT. Alfred pins -e PORT=8000 and maps
# host ports to container port 8000.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000
CMD ["python", "-m", "app"]
