FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ALPHADB_STREAMLIT_PORT=8501

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN apt-get update \
    && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir '.[dashboard]'

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/_stcore/health' % os.getenv('ALPHADB_STREAMLIT_PORT', '8501'), timeout=3).read()" || exit 1

CMD ["sh", "-c", "streamlit run src/alphadb/dashboard/app.py --server.address=0.0.0.0 --server.port=${ALPHADB_STREAMLIT_PORT:-8501} --server.headless=true"]
