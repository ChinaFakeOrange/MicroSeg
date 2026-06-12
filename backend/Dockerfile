# ---------------------------------------------------------------------------
# MicroSeg backend — CPU image.
# Runs the FastAPI API and the Celery worker for the lightweight jobs
# (interactive segmentation, morphometry, percolation, meshing). Deep-learning
# training/inference additionally needs the ML layer — see Dockerfile.gpu or
# set INSTALL_ML=1 to bake the CPU torch wheels in.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MICROSEG_DATA_DIR=/data

# SimpleITK / scikit-image / lightgbm need a few system libs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt requirements-ml.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Optionally bake the (CPU) deep-learning stack into the image.
ARG INSTALL_ML=0
RUN if [ "$INSTALL_ML" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends build-essential \
        && pip install -r requirements-ml.txt \
        && apt-get purge -y build-essential && apt-get autoremove -y \
        && rm -rf /var/lib/apt/lists/* ; \
    fi

COPY app ./app

# Non-root runtime user owning the data volume.
RUN useradd -m runner && mkdir -p /data && chown -R runner:runner /data /app
USER runner

EXPOSE 8000

# Default command runs the API; the worker overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
