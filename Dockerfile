# syntax=docker/dockerfile:1.7
FROM cgr.dev/chainguard/python:latest-dev@sha256:fe4dbb574f811d271ac002a3e0270659f69841738276ef2d0084323baf1d75df AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --chown=nonroot:nonroot pyproject.toml README.md /app/
COPY --chown=nonroot:nonroot src /app/src
RUN python -m pip install --user .
RUN mkdir -p /home/nonroot/.cache/quiet-chaos

FROM cgr.dev/chainguard/python:latest@sha256:f3e5face39b0acd813fae456df27b33bf6a6bffba5d201d15f6498138cb8fd96

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/nonroot/.local/bin:${PATH}"

WORKDIR /app

COPY --from=build --chown=nonroot:nonroot /home/nonroot/.local /home/nonroot/.local
COPY --from=build --chown=nonroot:nonroot /home/nonroot/.cache/quiet-chaos /home/nonroot/.cache/quiet-chaos
COPY --chown=nonroot:nonroot examples/config.toml /app/config.toml

USER nonroot
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "from quiet_chaos.health import check_health; check_health()"]

ENTRYPOINT ["quiet-chaos"]
CMD ["run", "--config", "/app/config.toml", "--cache-dir", "/home/nonroot/.cache/quiet-chaos"]
