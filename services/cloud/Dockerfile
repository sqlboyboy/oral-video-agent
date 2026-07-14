FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/data/huggingface

WORKDIR /app

RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i \
            -e 's|deb.debian.org|mirrors.cloud.tencent.com|g' \
            -e 's|security.debian.org|mirrors.cloud.tencent.com|g' \
            /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e 's|deb.debian.org|mirrors.cloud.tencent.com|g' \
            -e 's|security.debian.org|mirrors.cloud.tencent.com|g' \
            /etc/apt/sources.list; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        ffmpeg \
        fonts-noto-cjk \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -i https://mirrors.tencent.com/pypi/simple \
    cos-python-sdk-v5 \
    fastapi==0.115.6 \
    faster-whisper==1.1.1 \
    playwright==1.60.0 \
    "psycopg[binary]>=3.2.0" \
    pydantic==2.10.4 \
    python-dotenv \
    "redis>=5.2.0" \
    uvicorn[standard]==0.32.1

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
