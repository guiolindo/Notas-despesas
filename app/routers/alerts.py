from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.dependencies import get_current_user
from app.services.alert_service import get_alerts, get_alerts_summary


router = APIRouter()


@router.get("/summary")
def alerts_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """DB-05: retorna apenas contadores (5 COUNTs). Usado pelo badge
    do menu em toda pagina autenticada — antes chamava /alerts/ que
    materializava listas completas."""
    return get_alerts_summary(db, current_user)


@router.get("/")
def alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_alerts(db, current_user)
