# syntax=docker/dockerfile:1.7
# Analyzer API image: python slim + uv, served by uvicorn, data on the /data volume.
#
#   docker build -t stock-analyzer-server server/
#
# Behind a TLS-intercepting proxy, pass its CA as a build secret (never stored in a layer):
#   docker build --secret id=ca,src=/path/to/ca.crt ...

FROM python:3.11-slim AS build
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca SSL_CERT_FILE=/run/secrets/ca UV_NATIVE_TLS=1; fi && \
    pip install --no-cache-dir "uv==0.11.*" && \
    uv sync --frozen --no-dev --no-install-project
COPY stock_analyzer ./stock_analyzer
COPY prompts ./prompts
COPY data/companies.yaml ./data/companies.yaml
RUN --mount=type=secret,id=ca,required=false \
    if [ -s /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca UV_NATIVE_TLS=1; fi && \
    uv sync --frozen --no-dev

FROM python:3.11-slim
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app:app /data
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    ALLOW_LIVE=false
VOLUME ["/data"]
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status != 200)"
CMD ["uvicorn", "stock_analyzer.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
