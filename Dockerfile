# INFRA-06 (auditoria set/2026): imagem explicita, reprodutivel.
# Antes o Railway inferia via nixpacks — mudancas de versao invisiveis
# ao repo.
FROM python:3.12-slim

# Boas praticas: nao rodar como root.
RUN groupadd -r app && useradd -r -g app -m app

WORKDIR /app

# Deps do sistema: libpq pra psycopg2, curl pra healthcheck. Nada mais.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Instala deps Python — copia so o requirements primeiro pra cachear
# a camada quando so o codigo muda.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Codigo
COPY --chown=app:app . .

USER app

# Porta configurada via $PORT (Railway); default 8000 local.
ENV PORT=8000
EXPOSE 8000

# Healthcheck real — pega dependencies quando disponivel.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/health/ready || exit 1

# gunicorn com WEB_CONCURRENCY do env (INFRA-05) + timeouts (BE-02).
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT} --preload --timeout 60 --graceful-timeout 30"]
