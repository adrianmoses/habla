# syntax=docker/dockerfile:1

########## Builder ##########
FROM python:3.12-slim AS builder

# uv from the official image. Copying the binary into the SAME python:3.12-slim
# base used by the runtime stage guarantees the venv's interpreter symlink
# (/app/.venv/bin/python -> the base python) resolves identically downstream.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependency layer — cached until pyproject.toml / uv.lock change.
#   --no-dev             drop the [dependency-groups] dev group (pytest/ruff/mypy…).
#                        The eval/dev *extras* are already excluded (uv installs
#                        no extras without --extra/--all-extras).
#   --no-install-project install third-party deps only; app source runs from
#                        /app at runtime, so this layer is code-change-independent.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Bake the Spanish spaCy model INTO the venv site-packages (installs as the pip
# package `es_core_news_sm`, so it travels with the venv COPY below). Without it
# hable_ya/learner/vocabulary.py silently records no vocabulary ([]).
RUN /app/.venv/bin/python -m spacy download es_core_news_sm

########## Runtime ##########
FROM python:3.12-slim AS runtime

# onnxruntime (bundled Silero VAD + SmartTurn v3) needs libstdc++6; libgcc_s is
# already present in slim. NO model download at runtime — both ONNX files ship
# inside the pipecat wheel and load via importlib.resources.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user/group (fixed uid/gid so named-volume ownership is predictable).
RUN groupadd --system --gid 10001 app \
    && useradd  --system --uid 10001 --gid app --home-dir /app --no-create-home app

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HABLE_YA_RUNTIME_TURNS_PATH=/app/data/runtime_turns.jsonl \
    NLTK_DATA=/usr/local/share/nltk_data

# Venv (deps + spaCy model + bundled ONNX) from the builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Pipecat's sentence tokenizer (pipecat.utils.string) downloads NLTK 'punkt_tab'
# on first import and writes it to a cwd/HOME-relative dir the non-root user
# can't create. Pre-bake it at build into a world-readable path (NLTK_DATA above)
# so no runtime network/write is needed.
RUN python -m nltk.downloader -d "$NLTK_DATA" punkt_tab

# App source at the exact paths the boot path expects:
#   db/migrations.py: parents[2] == /app  =>  /app/alembic.ini
#   alembic.ini:      script_location %(here)s/hable_ya/db/alembic
# eval/ is a RUNTIME dependency (hable_ya imports eval.fixtures.schema +
# eval.scoring.recast — CEFR/profile schemas and Spanish lemmatization), not just
# an eval-harness package, so it must ship in the image.
COPY --chown=app:app hable_ya/   /app/hable_ya/
COPY --chown=app:app api/        /app/api/
COPY --chown=app:app eval/       /app/eval/
COPY --chown=app:app alembic.ini /app/alembic.ini

# App-owned, pre-created dir for the observation sink (append() does NOT mkdir).
# Backed by the `appdata` named volume in compose; a fresh named volume inherits
# this app:app ownership so the non-root process can write runtime_turns.jsonl.
RUN install -d -o app -g app /app/data

USER app
EXPOSE 8000

# Reuse #016 /health: 200 only when ready + db-live + no degraded provider.
# python:3.12-slim has no curl → urllib. A 503 raises HTTPError → non-zero exit
# → "unhealthy". start-period covers boot-time migrations (upgrade_to_head) +
# warmup_llm.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"]

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
