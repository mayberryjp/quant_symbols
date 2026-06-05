FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY quant_symbols ./quant_symbols
COPY alembic.ini ./
COPY alembic ./alembic
COPY migrations ./migrations
COPY tests ./tests

RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install -e ".[dev]"

CMD ["bash"]
