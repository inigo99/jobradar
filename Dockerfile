# JobRadar's dashboard in a container. Your data lives in the /data volume.
#
#   docker compose up -d        # then open http://localhost:8000
#
# The image includes Chromium for the HTML-template PDFs and the browsers the
# restricted sources use, so it is large (about 2 GB). The README has the
# details.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JOBRADAR_HOME=/data \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[all]" \
    && playwright install --with-deps chromium \
    && scrapling install \
    && useradd --create-home --uid 1000 jobradar \
    && mkdir -p /data && chown jobradar /data \
    && chmod -R a+rX /opt/browsers \
    && rm -rf /app/src /root/.cache

USER jobradar
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=1m --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"
# Listening on every interface inside the container; compose publishes the
# port on the host's loopback only.
CMD ["jobradar", "serve", "--host", "0.0.0.0", "--port", "8000"]
