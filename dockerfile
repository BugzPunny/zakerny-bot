FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the application code
COPY . .

# Create a non-root user and set permissions
RUN useradd -m botuser && \
    chown -R botuser:botuser /app && \
    chmod 755 /app

# Switch to the non-root user
USER botuser

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python", "bot.py"]
