FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends docker.io nodejs npm && rm -rf /var/lib/apt/lists/*
RUN npm install --global @openai/codex
COPY requirements-ml.txt requirements-chat.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt -r requirements-chat.txt
COPY . .
ENV ARCHITECTOR_CONTAINER=1 ARCHITECT_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "serve.py"]
