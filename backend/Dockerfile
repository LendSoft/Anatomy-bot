# syntax=docker/dockerfile:1.7
# Многостадийная сборка: base -> dev | prod

# ------------------------------------------------------------------- base
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tesseract с русским и английским — нужен для OCR отсканированных учебников;
# poppler-utils требуется pdf2image для растеризации страниц перед распознаванием
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# ------------------------------------------------------------------- dev
FROM base AS dev
# Исходники монтируются томом, копировать не нужно
ENV ENVIRONMENT=development
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]

# ------------------------------------------------------------------ prod
FROM base AS prod
ENV ENVIRONMENT=production

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Не работаем из-под root
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data/storage \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8080
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", "--bind", "0.0.0.0:8080", "--timeout", "300"]
