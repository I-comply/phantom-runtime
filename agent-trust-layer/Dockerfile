# Gateway image. Base pinned by digest (python:3.12-slim). Runs as non-root; no Docker socket needed.
FROM python@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ATL_DIR=/data ATL_EXECUTOR=subprocess
WORKDIR /app
COPY atl/ ./atl/
COPY capabilities.json ./
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
VOLUME /data
EXPOSE 8787
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/healthz',timeout=3)"
CMD ["sh", "-c", "[ -f /data/capabilities.json ] || cp /app/capabilities.json /data/; exec python -m atl serve --host 0.0.0.0"]
