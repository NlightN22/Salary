FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    APP_PUBLIC_URL=http://127.0.0.1:8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fontconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/salary_web/service_data/uploads \
    /app/salary_web/service_data/generated \
    /app/Report \
    /app/Data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

CMD ["sh", "-c", "echo \"Salary web is available at ${APP_PUBLIC_URL}\" && uvicorn salary_web.app:app --host 0.0.0.0 --port ${PORT}"]
