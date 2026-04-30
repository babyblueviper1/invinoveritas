FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_ONE_DATA_DIR=/data \
    AGENT_ONE_LOG_FILE=/data/agent_one.log

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent_one.py .
VOLUME ["/data"]

CMD ["python", "agent_one.py"]
