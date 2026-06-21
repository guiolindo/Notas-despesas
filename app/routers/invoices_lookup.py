"""Endpoints de lookup auxiliares: /directors e /lookup-cnpj/{cnpj}.

DEVE ser incluido ANTES do crud no facade pra que `/directors` (estatico)
nao seja capturado por `/{invoice_id}` (parametro). Mesma logica para
`/lookup-cnpj/{cnpj}`.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.dependencies import get_current_user
from app.services import invoice_service


router = APIRouter()


@router.get("/directors", response_model=list)
def get_directors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista diretores disponíveis com indicação de compatibilidade com o setor do usuário."""
    return invoice_service.get_available_directors(db, current_user)


@router.get("/lookup-cnpj/{cnpj}")
def lookup_cnpj_endpoint(
    cnpj: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Consulta dados do CNPJ via opencnpj.org (cache 6 meses).
    Retorna razao_social + nome_fantasia ou 404 se nao encontrado/invalido."""
    from app.services import document_service
    data = document_service.lookup_cnpj(db, cnpj)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CNPJ nao encontrado ou invalido.")
    return data
