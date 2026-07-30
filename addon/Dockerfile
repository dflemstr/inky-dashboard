# Self-contained: install the tool's serve half plus a headless Chromium.
# python:slim is multi-arch (arm64 for HA Yellow / Green / RPi CM4).
FROM python:3.13-slim-bookworm

# git is needed to pip-install the tool from the repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Disable font anti-aliasing so text renders pure black/white (1-bit): AA gray
# edges otherwise dither into speckle on the limited Spectra palette.
COPY local.conf /etc/fonts/local.conf

# Install the rendering half and a headless Chromium with its system deps.
RUN pip install --no-cache-dir \
        "inky-dashboard[serve] @ git+https://github.com/dflemstr/inky-dashboard" \
    && playwright install --with-deps chromium

COPY run.py /run.py
CMD ["python3", "/run.py"]
