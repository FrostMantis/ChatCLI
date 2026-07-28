FROM python:3.12-slim

# mariadb connector requires the C client library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmariadb-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5123 8765

CMD ["python", "run_server.py"]