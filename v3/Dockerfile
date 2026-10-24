# =============================================================================
# Assistente fatture v3 — immagine del container
#
#   docker build -t assistente-fatture .                  -> immagine di produzione (il bot Telegram)
#   docker build --target test -t assistente-fatture:test . -> esegue i test DENTRO il container
#
# Niente segreti nell'immagine: token e chiavi arrivano come variabili d'ambiente (--env-file),
# i dati e le credenziali Google come cartelle collegate da fuori (volumi). Vedi README, "Container".
# =============================================================================

# --- base: Python e un utente senza privilegi -----------------------------------
FROM python:3.13-slim-bookworm AS base
RUN useradd --create-home --home-dir /app app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app/app \
    CARTELLA_DATI=/dati \
    TZ=Europe/Rome

# --- dipendenze: installate dal lock file, versioni identiche al PC di sviluppo ---
FROM base AS dipendenze
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# --- test: stesse dipendenze + pytest, poi si eseguono i test ----------------------
FROM dipendenze AS test
RUN uv sync --frozen --no-install-project
COPY app ./app
COPY tests ./tests
COPY file_di_prova ./file_di_prova
COPY valutazione ./valutazione
RUN uv run --frozen pytest -q

# --- produzione: solo il codice e le librerie, senza pytest né file di prova -----
FROM base AS produzione
COPY --from=dipendenze /app/.venv /app/.venv
COPY app ./app
RUN mkdir -p /dati /app/segreti /app/log && chown -R app:app /dati /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
VOLUME ["/dati", "/app/segreti"]
# Il bot va lui a prendere i messaggi da Telegram (polling): nessuna porta da aprire.
CMD ["python", "app/avvio.py"]
