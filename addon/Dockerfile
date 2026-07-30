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

# Heavy, code-independent layer: the browser engine and its system deps. Cached
# across add-on version bumps so re-deploys don't re-download Chromium.
RUN pip install --no-cache-dir "playwright>=1.61.0" "aiohttp>=3.9" "pillow>=12.3.0" \
    && playwright install --with-deps chromium

# Home Assistant's frontend renders in Roboto (with Noto for broad glyph
# coverage). The slim base + Chromium deps only ship Liberation/DejaVu, so
# without these the dashboard falls back to a different face. Install them so
# text renders in the intended font.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-roboto fonts-noto-core \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# The tool itself. BUILD_VERSION (from config.yaml's version, passed by Supervisor)
# busts this layer, so bumping the add-on version re-fetches the latest code
# without rebuilding the browser layer above.
ARG BUILD_VERSION
RUN echo "inky-dashboard build ${BUILD_VERSION}" \
    && pip install --no-cache-dir --no-deps \
        "inky-dashboard @ git+https://github.com/dflemstr/inky-dashboard"

COPY run.py /run.py
CMD ["python3", "/run.py"]
