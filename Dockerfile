# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system quiet-chaos && adduser --system --ingroup quiet-chaos quiet-chaos

COPY pyproject.toml README.md /app/
COPY src /app/src
RUN pip install .

COPY examples/config.toml /app/config.toml
RUN mkdir -p /app/.cache/quiet-chaos && chown -R quiet-chaos:quiet-chaos /app

USER quiet-chaos
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080', timeout=3).read()"

ENTRYPOINT ["quiet-chaos"]
CMD ["run", "--config", "/app/config.toml"]
