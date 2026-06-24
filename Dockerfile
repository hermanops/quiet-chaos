# syntax=docker/dockerfile:1.7
FROM cgr.dev/chainguard/python:latest-dev AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
  PIP_NO_CACHE_DIR=1 \
  PATH="/home/nonroot/.local/bin:${PATH}"

WORKDIR /app

COPY --chown=nonroot:nonroot pyproject.toml README.md /app/
COPY --chown=nonroot:nonroot src /app/src
RUN python -m pip install --user .

COPY --chown=nonroot:nonroot examples/config.toml /app/config.toml
RUN mkdir -p /home/nonroot/.cache/quiet-chaos

USER nonroot
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080', timeout=3).read()"

ENTRYPOINT ["quiet-chaos"]
CMD ["run", "--config", "/app/config.toml", "--cache-dir", "/home/nonroot/.cache/quiet-chaos"]
