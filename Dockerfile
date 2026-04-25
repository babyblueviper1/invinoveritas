FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir mcp-proxy

COPY mcp_server.py .

ENV INVINO_API_KEY=""

CMD ["python", "mcp_server.py"]
