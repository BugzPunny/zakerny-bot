FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

RUN chmod a+w /app/zakerny.db || true

CMD ["python", "bot.py"]
