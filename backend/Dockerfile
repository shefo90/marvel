# The API and the worker: same image, different entry points.
#
# Two stages so the compiler toolchain psycopg2 and bcrypt need at build time
# does not travel to production. The runtime layer carries the installed
# packages and nothing that could compile anything.

# --- build ------------------------------------------------------------------
FROM python:3.12-slim AS build

# 3.12, not 3.14: psycopg2-binary publishes no 3.14 wheel, so a newer base image
# turns `pip install` into a source build that fails on a slim image.
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Installed into a virtualenv rather than the system interpreter, because a
# virtualenv is one directory that can be copied wholesale into the next stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied alone and installed before the source, so editing a route does not
# invalidate the dependency layer and reinstall everything.
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl for the healthcheck. Without it HEALTHCHECK has nothing to call, and a
# container that cannot report its own health makes `depends_on: healthy`
# meaningless for everything downstream.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

# Non-root. The API accepts uploaded files and decodes them with Pillow, which
# is the largest attack surface in the process; running that as root means an
# image-decode bug is a root bug.
RUN useradd --create-home --uid 10001 marvel
WORKDIR /app
COPY --chown=marvel:marvel . .

# Uploaded imagery. Created here with the right owner because the volume mounts
# over it as root otherwise, and the API then cannot write a single photograph.
RUN mkdir -p /var/lib/marvel/media && chown -R marvel:marvel /var/lib/marvel

USER marvel
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
