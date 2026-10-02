# Forge CLIP embedding sidecar. Wraps open_clip (ViT-B-32) in a small FastAPI
# service that speaks the embedding contract in
# backend/templates/runtime/embeddings.ts.
#
# Build: docker build -t forge-clip .
# Run:   docker run -d --name forge-clip -p 8001:8001 forge-clip

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch keeps the image ~1GB instead of ~5GB with CUDA.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1" "torchvision==0.20.1" \
 && pip install --no-cache-dir \
        "fastapi==0.115.5" \
        "uvicorn[standard]==0.32.1" \
        "pydantic==2.9.2" \
        "httpx==0.27.2" \
        "pillow==11.0.0" \
        "open_clip_torch==2.29.0"

# Bake the weights into the image: a container that downloads ~600MB on its
# first request fails that request.
ENV CLIP_MODEL=ViT-B-32 CLIP_PRETRAINED=laion2b_s34b_b79k
RUN python -c "import open_clip; open_clip.create_model_and_transforms('ViT-B-32', pretrained='laion2b_s34b_b79k')"

COPY server.py /app/server.py

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
