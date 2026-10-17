# --- build the web app
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- the service
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
ARG WITH_EMBEDDINGS=0
RUN if [ "$WITH_EMBEDDINGS" = "1" ]; then pip install --no-cache-dir fastembed; fi   # optional: --build-arg WITH_EMBEDDINGS=1 and GRAPHMEM_EMBEDDINGS=1
# speech model baked in so the first voice note does not wait on a download
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"
COPY graphmem ./graphmem
COPY carecircle ./carecircle
COPY --from=web /web/dist ./web/dist
COPY scripts ./scripts
ENV HOST=0.0.0.0 PORT=8000 FALKORDB_HOST=falkordb PYTHONPATH=/app
EXPOSE 8000
CMD ["python", "scripts/boot.py"]
