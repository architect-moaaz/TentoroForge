# Forge PaddleOCR sidecar. Wraps PaddleOCR in a small FastAPI service that
# speaks the ocr_document contract (see OCR_SIDECAR.md).
#
# Build: docker build -t forge-paddleocr .
# Run:   docker run -d --name forge-paddleocr -p 8000:8000 forge-paddleocr

FROM python:3.11-slim

# System deps for PaddlePaddle + PaddleOCR (OpenCV needs libgl/libglib).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python deps in a single layer. paddlepaddle wheel is large (~500MB);
# pin the versions we've tested against.
RUN pip install --no-cache-dir \
        "fastapi==0.115.5" \
        "uvicorn[standard]==0.32.1" \
        "pydantic==2.9.2" \
        "httpx==0.27.2" \
        "paddlepaddle==2.6.2" \
        "paddleocr==2.9.1"

COPY server.py /app/server.py

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
