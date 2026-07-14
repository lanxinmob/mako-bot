FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system mako && useradd --system --gid mako --create-home mako
WORKDIR /app

COPY --chown=mako:mako pyproject.toml requirements.txt README.md LICENSE ./
COPY --chown=mako:mako src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

RUN mkdir -p /app/logs && chown -R mako:mako /app
USER mako

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1

CMD ["mako-bot"]
