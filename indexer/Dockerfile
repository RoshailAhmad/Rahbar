# RAHBAR indexer image: the Job's image and the ONLY writer to Chroma.
# Build context: indexer/  ->  make stage-corpus && docker build -t rahbar-indexer:dev indexer
# `make stage-corpus` copies corpus/raw/ into indexer/corpus/ and eval/fixtures/ into
# indexer/fixtures/ (both gitignored), so the documents are baked into this image.
# CORPUS_DIR=/corpus for the real corpus, CORPUS_DIR=/fixtures for CI.

FROM python:3.12.8-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.12.8-slim-bookworm
# OCR for the scanned PDF (corpus property 3): tesseract + poppler for pdf2image.
# OS patches first (Trivy fails CI on fixable HIGH/CRITICAL), then the OCR tools.
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    CORPUS_DIR=/corpus
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY pipeline ./pipeline
COPY corpus/ /corpus/
COPY fixtures/ /fixtures/
USER 10001
# The Job/CronJob pass extra flags as args, e.g. ["--dummy"] in week 1.
ENTRYPOINT ["python", "-m", "pipeline.run"]
