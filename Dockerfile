FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy app
COPY . .
RUN pip install --no-cache-dir -e .

# Data volume
VOLUME /data
ENV XEN_DATA_DIR=/data

EXPOSE 7600

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7600/api/sessions')" || exit 1

CMD ["uvicorn", "xen.server:app", "--host", "0.0.0.0", "--port", "7600"]
