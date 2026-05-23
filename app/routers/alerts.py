from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.dependencies import get_current_user
from app.services.alert_service import get_alerts


router = APIRouter()


@router.get("/")
def alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_alerts(db, current_user)
