# INFRA-05 (auditoria set/2026): workers configuraveis via env WEB_CONCURRENCY.
# gunicorn le a variavel automaticamente quando -w nao e passado.
# Default 2 (mantem comportamento anterior); em prod dimensionar 2*cores+1.
web: gunicorn app.main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --preload --timeout 60 --graceful-timeout 30
