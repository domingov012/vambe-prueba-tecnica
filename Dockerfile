# Backend image. Also bakes the built frontend into /home/app/static so this
# single image can serve the whole app on its own (Hugging Face Spaces and most
# free hosts deploy one image). Under docker-compose the nginx container serves
# those assets instead and the baked copy simply goes unused — same image both
# ways, no second build path to keep in sync. See app/main.py for the mount.

# ---- frontend build -------------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /frontend
# package files first so `npm ci` caches across source-only changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- python dependencies --------------------------------------------------
# Built in a throwaway stage so pip and its build tooling never reach the
# runtime image; only the finished virtualenv is copied forward.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---- runtime --------------------------------------------------------------
# slim, not alpine: musl has no manylinux wheels for pydantic-core / pymongo /
# uvloop, so alpine would compile them from source — slower build, bigger image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# uid 1000 is what Hugging Face Spaces expects the container to run as.
RUN useradd --create-home --uid 1000 app
WORKDIR /home/app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app scripts/ ./scripts/
COPY --from=frontend --chown=app:app /frontend/dist ./static/

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/health')" || exit 1

# Single uvicorn worker, deliberately: the enrichment queue is an in-process
# asyncio.Queue (app/llm/jobs.py), so a second worker process would get its own
# queue and its own worker loop. Don't add --workers, and don't scale replicas.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
