# RAHBAR api image. Build context: api/   ->   docker build -t rahbar-api:dev api
# Two stages: dependencies are installed in a throwaway stage, so pip and build
# leftovers never reach the final image.

FROM python:3.12.8-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.12.8-slim-bookworm
# HOME=/tmp: the root filesystem is read-only on the cluster and /tmp is an emptyDir.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY app ./app
# Numeric UID so Kubernetes can verify runAsNonRoot without reading /etc/passwd.
USER 10001
EXPOSE 8000
# Exec form: uvicorn is PID 1 and receives SIGTERM directly, then drains for 20 s.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20"]
