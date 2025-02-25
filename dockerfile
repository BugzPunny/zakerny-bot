FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libssl-dev \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN useradd -m botuser && \
    chown -R botuser:botuser /app && \
    chmod 755 /app

USER botuser

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "bot.py"]
