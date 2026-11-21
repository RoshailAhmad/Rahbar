# RAHBAR evaluation image (Assignment 03, Part F2). Build context: eval/
#   docker build -t rahbar-eval:dev eval
# Runs eval/job.py: the three-level suite against an api Service, then the release gate.
FROM python:3.12.8-slim-bookworm
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
COPY requirements.txt .
RUN pip install -r requirements.txt
WORKDIR /eval
COPY . .
USER 10001
CMD ["python", "job.py"]
