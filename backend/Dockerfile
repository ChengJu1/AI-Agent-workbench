# Match the Python version used by this project's existing virtual environment.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/appuser \
    PLAYWRIGHT_BROWSERS_PATH=/opt/workbench-browsers

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

WORKDIR /workspace/backend

# Dependency layers stay cached when only application code changes.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt \
    && python -m playwright install --with-deps chromium

COPY --chown=appuser:appuser . .
RUN chown -R appuser:appuser /workspace

# The app and its tool subprocesses run as an ordinary user.
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
