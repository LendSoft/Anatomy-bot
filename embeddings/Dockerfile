FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/models

WORKDIR /srv

# torch ставим отдельно из CPU-индекса: колёса с CUDA весят ~2.5 ГБ и здесь не нужны
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8100
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100"]
