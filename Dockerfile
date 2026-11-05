# Pricing web service. It serves the aggregated tables in outputs/v1/ and needs no MEPS data.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    MODEL_VERSION=v1

WORKDIR /app

COPY requirements-service.txt .
RUN pip install --no-cache-dir -r requirements-service.txt

COPY src/health_pricing/__init__.py src/health_pricing/__init__.py
COPY src/health_pricing/rating src/health_pricing/rating
COPY src/health_pricing/service src/health_pricing/service
COPY outputs/v1 outputs/v1

RUN useradd --create-home --uid 10001 service
USER service

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "health_pricing.service.app:app", "--host", "0.0.0.0", "--port", "8000"]
