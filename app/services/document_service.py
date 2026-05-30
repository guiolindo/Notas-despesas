"""Validacao e consulta de CPF/CNPJ.

CPF: 11 digitos, validacao Mod 11 com pesos descrescentes.
CNPJ: 14 digitos, validacao Mod 11 com pesos especificos.
Algoritmos sao oficiais da Receita Federal — nao mudam.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

CNPJ_CACHE_TTL_DAYS = 180  # 6 meses


def strip_non_digits(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\D", "", value)


# ─── Validacao CPF ──────────────────────────────────────────────────────────

def validate_cpf(cpf: str | None) -> bool:
    """Valida CPF via algoritmo oficial Mod 11."""
    cpf = strip_non_digits(cpf)
    if len(cpf) != 11:
        return False
    # Sequencias invalidas (000.000.000-00, 111.111.111-11, etc.)
    if cpf == cpf[0] * 11:
        return False
    # Primeiro digito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = soma % 11
    dv1 = 0 if resto < 2 else 11 - resto
    if dv1 != int(cpf[9]):
        return False
    # Segundo digito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = soma % 11
    dv2 = 0 if resto < 2 else 11 - resto
    return dv2 == int(cpf[10])


def format_cpf(cpf: str) -> str:
    cpf = strip_non_digits(cpf)
    if len(cpf) != 11:
        return cpf
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def mask_cpf(cpf: str | None) -> str:
    """Para /verify publico: '123.***.***-01'."""
    digits = strip_non_digits(cpf)
    if len(digits) != 11:
        return "***"
    return f"{digits[:3]}.***.***-{digits[9:]}"


# ─── Validacao CNPJ ─────────────────────────────────────────────────────────

CNPJ_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
CNPJ_WEIGHTS_2 = [6] + CNPJ_WEIGHTS_1


def validate_cnpj(cnpj: str | None) -> bool:
    """Valida CNPJ via algoritmo oficial Mod 11."""
    cnpj = strip_non_digits(cnpj)
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False
    # Primeiro DV
    soma = sum(int(cnpj[i]) * CNPJ_WEIGHTS_1[i] for i in range(12))
    resto = soma % 11
    dv1 = 0 if resto < 2 else 11 - resto
    if dv1 != int(cnpj[12]):
        return False
    # Segundo DV
    soma = sum(int(cnpj[i]) * CNPJ_WEIGHTS_2[i] for i in range(13))
    resto = soma % 11
    dv2 = 0 if resto < 2 else 11 - resto
    return dv2 == int(cnpj[13])


def format_cnpj(cnpj: str) -> str:
    cnpj = strip_non_digits(cnpj)
    if len(cnpj) != 14:
        return cnpj
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def mask_cnpj(cnpj: str | None) -> str:
    """Para /verify publico: '12.***.***/****-90'."""
    digits = strip_non_digits(cnpj)
    if len(digits) != 14:
        return "***"
    return f"{digits[:2]}.***.***/****-{digits[12:]}"


# ─── Detecta tipo ───────────────────────────────────────────────────────────

def detect_document_type(value: str | None) -> str | None:
    """Retorna 'CPF', 'CNPJ' ou None."""
    digits = strip_non_digits(value)
    if len(digits) == 11:
        return "CPF" if validate_cpf(digits) else None
    if len(digits) == 14:
        return "CNPJ" if validate_cnpj(digits) else None
    return None


# ─── Consulta opencnpj.org com cache local 6 meses ──────────────────────────

def lookup_cnpj(db: Session, cnpj: str) -> dict | None:
    """Busca dados do CNPJ — primeiro no cache, depois na API.

    Retorna {'cnpj': str, 'razao_social': str, 'nome_fantasia': str} ou None.
    Cache de 180 dias. API: api.opencnpj.org/<cnpj>.
    """
    from app.models import CnpjCache

    digits = strip_non_digits(cnpj)
    if not validate_cnpj(digits):
        return None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=CNPJ_CACHE_TTL_DAYS)

    # 1) Verifica cache
    cached = db.query(CnpjCache).filter(CnpjCache.cnpj == digits).first()
    if cached:
        cached_at = cached.cached_at
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        if cached_at > cutoff:
            return {
                "cnpj": cached.cnpj,
                "razao_social": cached.razao_social or "",
                "nome_fantasia": cached.nome_fantasia or "",
                "cached": True,
            }

    # 2) Chama API
    url = f"https://api.opencnpj.org/{digits}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Economart-Notas/1.0 (+https://economart.com.br)",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning(f"[cnpj] falha ao consultar {digits}: {exc}")
        return None

    razao = (data.get("razao_social") or "")[:255]
    fantasia = (data.get("nome_fantasia") or "")[:255]

    # 3) Atualiza cache (upsert simples)
    if cached:
        cached.razao_social = razao
        cached.nome_fantasia = fantasia
        cached.cached_at = now
    else:
        db.add(CnpjCache(
            cnpj=digits,
            razao_social=razao,
            nome_fantasia=fantasia,
            cached_at=now,
        ))
    db.commit()
    return {
        "cnpj": digits,
        "razao_social": razao,
        "nome_fantasia": fantasia,
        "cached": False,
    }
