"""Endpoints especificos do perfil CONTAS_A_PAGAR.

Hoje so existe /stats — contador de comprovantes reimpressos nas ultimas
24h pelo proprio usuario, usado no badge 'Conferidas hoje' do dashboard.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApprovalAction, ApprovalHistory, User
from app.security.dependencies import get_current_user


router = APIRouter()


@router.get("/api/contas-a-pagar/stats")
def stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Quantidade de notas que o usuario logado conferiu (reimprimiu o
    comprovante) nas ultimas 24h. Janela rolante simples — suficiente para
    o badge de turno e evita complicacao de fuso na borda da meia-noite.
    """
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    count = (
        db.query(func.count(ApprovalHistory.id))
        .filter(
            ApprovalHistory.user_id == current_user.id,
            ApprovalHistory.action == ApprovalAction.PRINTED,
            ApprovalHistory.timestamp >= window_start,
        )
        .scalar()
        or 0
    )
    return {"conferred_today": int(count)}
