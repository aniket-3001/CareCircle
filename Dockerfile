FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir falkordb fastapi "uvicorn[standard]" mcp httpx
COPY graphmem ./graphmem
ENV HOST=0.0.0.0 PORT=8000 FALKORDB_HOST=falkordb
EXPOSE 8000
CMD ["python", "-m", "graphmem.api"]
