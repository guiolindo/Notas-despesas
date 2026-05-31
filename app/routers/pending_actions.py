"""Endpoints para acoes administrativas pendentes (janela 24h).

Fluxo:
- Admin solicita acao sensivel via PUT /admin/users/{id} ou
  POST /admin/users/{id}/reset-password (codigo no admin.py cria
  PendingAdminAction em vez de executar direto).
- Alvo (diretor) e outros diretores recebem email + banner no dashboard.
- POST /pending-actions/{id}/cancel: alvo ou outro diretor cancela.
- POST /pending-actions/run-due: chamado periodicamente (ou na hidratacao
  de dashboard) executa as pendentes vencidas.
- GET /pending-actions/me: lista pendentes que afetam o usuario atual
  (pra renderizar banner vermelho).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AuditLog,
    PendingActionStatus,
    PendingActionType,
    PendingAdminAction,
    User,
    UserRole,
)
from app.security.dependencies import get_current_user
from app.security.hashing import pseudonymize_ip


router = APIRouter()


# ─── Schemas ─────────────────────────────────────────────────────────────


class PendingActionView(BaseModel):
    id: str
    action_type: str
    action_label: str
    target_user_id: str
    target_name: Optional[str]
    requested_by_id: str
    requested_by_name: Optional[str]
    requested_at: str
    effective_at: str
    seconds_remaining: int
    status: str
    reason: Optional[str]


class CancelRequest(BaseModel):
    reason: Optional[str] = None


ACTION_LABELS = {
    PendingActionType.DEACTIVATE_DIRECTOR.value: "Desativacao de diretor",
    PendingActionType.ENCERRAR_DIRECTOR.value: "Encerramento de conta de diretor",
    PendingActionType.RESET_PASSWORD_DIRECTOR.value: "Redefinicao de senha de diretor",
}


# ─── Helpers ─────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(db: Session, request: Request, user_id: str, action: str, resource_id: str, detail: str) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action=action,
            resource_type="PENDING_ADMIN_ACTION",
            resource_id=resource_id,
            ip_address=pseudonymize_ip(request.client.host if request.client else None),
            source_port=request.client.port if request.client else None,
            http_method=request.method,
            user_agent=request.headers.get("user-agent"),
            timestamp=_now(),
            success=True,
            detail=detail,
        )
    )


def _serialize(pa: PendingAdminAction) -> dict:
    eff = pa.effective_at
    if eff.tzinfo is None:
        eff = eff.replace(tzinfo=timezone.utc)
    remaining = int((eff - _now()).total_seconds())
    return {
        "id": pa.id,
        "action_type": pa.action_type.value,
        "action_label": ACTION_LABELS.get(pa.action_type.value, pa.action_type.value),
        "target_user_id": pa.target_user_id,
        "target_name": pa.target.name if pa.target else None,
        "requested_by_id": pa.requested_by_id,
        "requested_by_name": pa.requested_by.name if pa.requested_by else None,
        "requested_at": pa.requested_at.replace(tzinfo=timezone.utc).isoformat()
            if pa.requested_at and pa.requested_at.tzinfo is None
            else (pa.requested_at.isoformat() if pa.requested_at else None),
        "effective_at": eff.isoformat(),
        "seconds_remaining": max(remaining, 0),
        "status": pa.status.value,
        "reason": pa.reason,
    }


def _execute_action(db: Session, pa: PendingAdminAction) -> None:
    """Executa o efeito real da acao pendente (chamado quando expira)."""
    user = db.query(User).filter(User.id == pa.target_user_id).first()
    if not user or user.role != UserRole.DIRECTOR:
        # Estado mudou no meio do caminho — marca como executado sem efeito
        return
    if pa.action_type == PendingActionType.DEACTIVATE_DIRECTOR:
        user.is_active = False
    elif pa.action_type == PendingActionType.ENCERRAR_DIRECTOR:
        # Encerramento real fica delegado ao admin re-executar via
        # /admin/users/{id}/anonymize APOS a janela. Aqui so libera o
        # bloqueio — admin precisa confirmar manualmente desativando
        # antes (anonymize exige is_active=False).
        user.is_active = False
    elif pa.action_type == PendingActionType.RESET_PASSWORD_DIRECTOR:
        # Senha temporaria ja foi setada via extra; aqui so forca troca.
        user.must_change_password = True


def run_due_actions(db: Session) -> int:
    """Executa todas as pendentes cujo effective_at ja passou. Retorna
    quantidade executada. Idempotente — pode ser chamado quantas vezes."""
    now = _now()
    due = (
        db.query(PendingAdminAction)
        .filter(
            PendingAdminAction.status == PendingActionStatus.PENDING,
            PendingAdminAction.effective_at <= now,
        )
        .all()
    )
    for pa in due:
        _execute_action(db, pa)
        pa.status = PendingActionStatus.EXECUTED
        pa.executed_at = now
    if due:
        db.commit()
    return len(due)


# ─── Endpoints ────────────────────────────────────────────────────────────


@router.get("/api/pending-actions/me")
def list_my_pending_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista pendentes que afetam o usuario logado (target). Usado no
    banner vermelho do dashboard. Inclui executar lazy de pendentes
    expiradas pra estado nao ficar 'stale'."""
    run_due_actions(db)
    items = (
        db.query(PendingAdminAction)
        .filter(
            PendingAdminAction.target_user_id == current_user.id,
            PendingAdminAction.status == PendingActionStatus.PENDING,
        )
        .order_by(PendingAdminAction.effective_at.asc())
        .all()
    )
    return [_serialize(i) for i in items]


@router.get("/api/pending-actions/visible")
def list_visible_pending_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista pendentes que diretores/admins podem ver e atuar (peer review).
    Cada item ganha can_confirm/can_cancel pra UI decidir os botoes:

    - target sempre pode cancelar (mas nunca confirmar)
    - peer director pode cancelar E confirmar
    - admin pode confirmar (sempre, exceto se foi o solicitante) e
      cancelar (se nao foi solicitante)
    - solicitante nao pode nem confirmar nem cancelar (auto-aprovacao)
    """
    if current_user.role.value not in {"DIRECTOR", "ADMIN"}:
        return []
    run_due_actions(db)
    items = (
        db.query(PendingAdminAction)
        .filter(PendingAdminAction.status == PendingActionStatus.PENDING)
        .order_by(PendingAdminAction.effective_at.asc())
        .all()
    )

    out = []
    for pa in items:
        is_target = current_user.id == pa.target_user_id
        is_solicitante = current_user.id == pa.requested_by_id
        is_peer_director = (
            current_user.role == UserRole.DIRECTOR
            and current_user.is_active
            and not is_target
        )
        is_neutral_admin = current_user.role == UserRole.ADMIN and not is_solicitante
        can_confirm = (is_peer_director or is_neutral_admin) and not is_target and not is_solicitante
        can_cancel = is_target or is_peer_director or is_neutral_admin
        serialized = _serialize(pa)
        serialized["can_confirm"] = can_confirm
        serialized["can_cancel"] = can_cancel
        serialized["is_target"] = is_target
        out.append(serialized)
    return out


@router.post("/api/pending-actions/{action_id}/cancel")
def cancel_pending_action(
    action_id: str,
    body: CancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancela uma acao pendente. Pode ser feito pelo:
    - proprio target (target_user_id == current_user.id)
    - qualquer OUTRO diretor ativo (peer veto)
    - qualquer admin que NAO seja o solicitante (anti auto-aprovacao)
    """
    pa = db.query(PendingAdminAction).filter(PendingAdminAction.id == action_id).first()
    if not pa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acao nao encontrada.")
    if pa.status != PendingActionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta acao ja foi cancelada ou executada.",
        )

    is_target = current_user.id == pa.target_user_id
    is_peer_director = (
        current_user.role == UserRole.DIRECTOR
        and current_user.is_active
        and current_user.id != pa.target_user_id
    )
    is_neutral_admin = (
        current_user.role == UserRole.ADMIN
        and current_user.id != pa.requested_by_id
    )
    if not (is_target or is_peer_director or is_neutral_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voce nao tem permissao para cancelar esta acao.",
        )

    pa.status = PendingActionStatus.CANCELLED
    pa.cancelled_by_id = current_user.id
    pa.cancelled_at = _now()
    pa.cancel_reason = (body.reason or "").strip() or None

    _audit(
        db, request, current_user.id,
        "CANCEL_PENDING_ADMIN_ACTION",
        pa.id,
        f"Cancelou acao {pa.action_type.value} contra {pa.target_user_id} (solicitada por {pa.requested_by_id}).",
    )
    db.commit()

    # Notifica o solicitante e o target (best-effort)
    try:
        from app.services import email_service
        solicit = db.query(User).filter(User.id == pa.requested_by_id).first()
        target = pa.target
        if solicit and solicit.email:
            email_service.send_email_async(
                solicit.email,
                subject=f"Sua solicitacao foi cancelada: {ACTION_LABELS.get(pa.action_type.value, '')}",
                html=f"<p>Ola {solicit.name},</p><p>{current_user.name} cancelou sua solicitacao "
                     f"<strong>{ACTION_LABELS.get(pa.action_type.value, pa.action_type.value)}</strong> "
                     f"contra <strong>{target.name if target else '?'}</strong>.</p>"
                     f"<p>Motivo informado: {pa.cancel_reason or '(nao informado)'}</p>",
            )
    except Exception:  # noqa: BLE001
        pass

    return {"status": "ok", "message": "Acao cancelada."}


@router.post("/api/pending-actions/{action_id}/confirm")
def confirm_pending_action(
    action_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confirma uma pending antecipadamente — executa imediatamente sem
    esperar as 24h. Caso de uso: demissao real do diretor. Outro diretor
    ou um admin neutro confirma que a acao e legitima.

    Quem pode confirmar:
    - Qualquer diretor ativo que NAO seja o target
    - Qualquer admin que NAO seja o solicitante (anti auto-aprovacao)

    Diferente do cancel: target NAO pode confirmar sua propria desativacao
    (impede um admin malicioso de coagir o diretor a 'apertar OK')."""
    pa = db.query(PendingAdminAction).filter(PendingAdminAction.id == action_id).first()
    if not pa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Acao nao encontrada.")
    if pa.status != PendingActionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta acao ja foi cancelada ou executada.",
        )
    if current_user.id == pa.target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voce nao pode confirmar sua propria desativacao.",
        )
    if current_user.id == pa.requested_by_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O solicitante nao pode confirmar a propria solicitacao.",
        )
    is_peer_director = current_user.role == UserRole.DIRECTOR and current_user.is_active
    is_admin = current_user.role == UserRole.ADMIN
    if not (is_peer_director or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas diretores ou administradores podem confirmar esta acao.",
        )

    _execute_action(db, pa)
    pa.status = PendingActionStatus.EXECUTED
    pa.executed_at = _now()
    pa.executed_by_id = current_user.id

    _audit(
        db, request, current_user.id,
        "CONFIRM_PENDING_ADMIN_ACTION",
        pa.id,
        f"Confirmou execucao de {pa.action_type.value} contra {pa.target_user_id} "
        f"(solicitada por {pa.requested_by_id}). Aplicado imediatamente.",
    )
    db.commit()

    # Notifica solicitante e target
    try:
        from app.services import email_service
        for uid in [pa.requested_by_id, pa.target_user_id]:
            recipient = db.query(User).filter(User.id == uid).first()
            if recipient and recipient.email and not recipient.email.endswith("@desligado.local"):
                email_service.send_email_async(
                    recipient.email,
                    subject=f"Acao confirmada e aplicada: {ACTION_LABELS.get(pa.action_type.value, '')}",
                    html=f"<p>Ola {recipient.name},</p><p><strong>{current_user.name}</strong> "
                         f"confirmou a execucao da acao "
                         f"<strong>{ACTION_LABELS.get(pa.action_type.value, pa.action_type.value)}</strong>. "
                         f"O efeito foi aplicado imediatamente, sem esperar as 24h.</p>",
                )
    except Exception:  # noqa: BLE001
        pass

    return {"status": "ok", "message": "Acao confirmada e executada."}


@router.post("/api/pending-actions/run-due")
def run_due_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Executa pendentes vencidas. Chamado pelo cron interno OU pelo
    proprio frontend (no carregamento de dashboard) — idempotente."""
    n = run_due_actions(db)
    return {"executed": n}
