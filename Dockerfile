FROM python:3.12-slim

# stdout をバッファリングせず、`docker logs` で同期の進捗をリアルタイムに確認できるようにする。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SYNC_INTERVAL_SECONDS=1800 \
    OMRON_SYNC_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["python", "-m", "app.scheduler"]
