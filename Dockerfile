# =============================================================
# HookReel — Dockerfile
# Base: python:3.11-slim (lightweight, no desktop packages)
# =============================================================
FROM python:3.11-slim
# -------------------------------------------------------
# Install system-level dependencies.
# libclamav-dev is needed so pyclamd can talk to ClamAV.
# gcc and libffi-dev are needed to compile some Python packages.
# curl is useful for debugging inside the container.
# ffmpeg is needed for HLS streaming (Phase 6.5 Tier 2).
# -------------------------------------------------------
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    libclamav-dev \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# -------------------------------------------------------
# Set the working directory inside the container.
# All subsequent commands run from here.
# -------------------------------------------------------
WORKDIR /hookreel
# -------------------------------------------------------
# Copy and install Python dependencies first.
# Docker caches this layer — rebuilds are faster when
# only app code changes (not requirements).
# -------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# -------------------------------------------------------
# Copy the application code into the container.
# -------------------------------------------------------
COPY app/ ./app/
COPY main.py .
COPY test_pipeline.py .
COPY test_phase7b.py .
COPY test_patch1.py .
COPY test_patch2.py .
COPY test_phase5.py .
COPY test_phase6.py .
COPY test_phase65.py .
COPY test_phase66.py .
COPY test_phase8.py .
COPY test_v1_1.py .
COPY import_library.py .
COPY setup.py .
COPY uninstall.py .
COPY docker-compose.dev.yml .
COPY CONTRIBUTING.md .
COPY .github/ ./.github/
# -------------------------------------------------------
# Expose port 8765 — reserved for the web UI (Phase 5+).
# -------------------------------------------------------
EXPOSE 8765
# -------------------------------------------------------
# Start HookReel when the container launches.
# -------------------------------------------------------
ENTRYPOINT ["python", "main.py"]
