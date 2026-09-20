"""Circuit breaker in-process para dependencias externas.

BE-05 (auditoria set/2026): sem isso, indisponibilidade de servico
externo (R2, opencnpj, Resend) fazia cada requisicao esperar o timeout
inteiro antes de falhar — atacante ou instabilidade real amplificava
custo. Agora, apos N falhas consecutivas, o breaker abre e rejeita
chamadas imediatamente por RESET_SECONDS. Depois entra em half-open e
tenta 1 chamada de teste; sucesso fecha, falha reabre.

Usar via context manager:
    breaker = get_breaker("r2")
    try:
        with breaker.call():
            client.put_object(...)
    except BreakerOpen:
        raise HTTPException(503, "Storage temporariamente indisponivel")

Stateful in-process; multi-worker gunicorn tem breakers independentes
(aceitavel — cada worker aprende sozinho).
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class BreakerOpen(RuntimeError):
    """Breaker aberto — rejeicao rapida sem tentar a operacao."""


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5      # falhas consecutivas antes de abrir
    reset_seconds: float = 30.0     # tempo em open antes de tentar half-open
    _failures: int = 0
    _opened_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at == 0:
                return False
            # Half-open: passou o reset — permite 1 tentativa
            return (time.monotonic() - self._opened_at) < self.reset_seconds

    def record_success(self) -> None:
        with self._lock:
            if self._failures or self._opened_at:
                logger.info("[breaker:%s] fechado apos sucesso", self.name)
            self._failures = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold and self._opened_at == 0:
                self._opened_at = time.monotonic()
                logger.warning(
                    "[breaker:%s] ABRIU apos %d falhas consecutivas",
                    self.name, self._failures,
                )

    @contextmanager
    def call(self):
        if self.is_open:
            raise BreakerOpen(f"circuit breaker '{self.name}' aberto")
        try:
            yield
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()


_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Retorna breaker singleton pelo nome. kwargs so aplicam na primeira
    criacao (nao reconfigura breaker existente)."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(name=name, **kwargs)
        return _registry[name]
