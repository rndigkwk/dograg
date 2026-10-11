# syntax=docker/dockerfile:1.10
# RagDog for Google Cloud Run (Streamlit Community Cloud keeps running from the repository as is).
#
#   docker build --secret id=hf_token,env=HF_TOKEN -t ragdog .
#   docker run --rm -p 8080:8080 --env-file .env ragdog
#
# The private data and the fine-tuned embedding model are downloaded at build time
# (scripts/prefetch_image_assets.py), so the image holds AI Hub-derived files: push it only to
# a private registry (Artifact Registry), never to a public one.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/app/.hf \
    RAGDOG_CONTAINER=1

WORKDIR /app

# Dependencies first: this layer changes only with uv.lock (no torch: the app embeds with ONNX).
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Private data: downloaded again only when its revision (src/private_data.py) changes.
COPY src/settings.py src/private_data.py src/
COPY scripts/prefetch_image_assets.py scripts/
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN \
    python scripts/prefetch_image_assets.py data

COPY . .
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN \
    python scripts/prefetch_image_assets.py model

# Everything is in the image now; nothing is fetched from the Hugging Face Hub at run time.
ENV HF_HUB_OFFLINE=1

EXPOSE 8080
# Cloud Run sets PORT; /_stcore/health answers once the server is up.
CMD ["sh", "-c", "exec streamlit run main.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true"]
