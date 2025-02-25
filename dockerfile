FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m botuser

USER botuser

RUN chmod a+w /app/zakerny.db || true

CMD ["python", "bot.py"]
