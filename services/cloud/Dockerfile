FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -i https://mirrors.tencent.com/pypi/simple \
    cos-python-sdk-v5 \
    fastapi==0.115.6 \
    "psycopg[binary]>=3.2.0" \
    pydantic==2.10.4 \
    python-dotenv \
    "redis>=5.2.0" \
    uvicorn[standard]==0.32.1

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
