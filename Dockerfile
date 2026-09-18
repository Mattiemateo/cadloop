# Deployment profile: provided but not built/tested in the delivery environment.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/cadloop
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[cadquery,build123d]'
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/mpl OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
USER 65532:65532
CMD ["python", "-m", "cadloop", "doctor"]
