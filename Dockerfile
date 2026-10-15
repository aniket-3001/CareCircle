FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir falkordb fastapi "uvicorn[standard]" mcp httpx
ARG WITH_EMBEDDINGS=0
RUN if [ "$WITH_EMBEDDINGS" = "1" ]; then pip install --no-cache-dir fastembed; fi   # optional: --build-arg WITH_EMBEDDINGS=1 and GRAPHMEM_EMBEDDINGS=1
COPY graphmem ./graphmem
ENV HOST=0.0.0.0 PORT=8000 FALKORDB_HOST=falkordb
EXPOSE 8000
CMD ["python", "-m", "graphmem.api"]
