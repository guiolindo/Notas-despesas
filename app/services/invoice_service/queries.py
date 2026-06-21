"""Queries de leitura sobre Invoice: visibilidade por role, busca por id,
listagem paginada com filtros."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ApprovalHistory,
    Invoice,
    InvoiceStatus,
    User,
    UserRole,
)


def _invoice_options() -> tuple:
    """Eager loading completo — usado em /api/invoices/{id} (detail) e por
    listagens que precisam montar timeline + anexos no MESMO payload."""
    return (
        selectinload(Invoice.approval_history).selectinload(ApprovalHistory.user),
        selectinload(Invoice.created_by).selectinload(User.department_obj),
        selectinload(Invoice.manager),
        selectinload(Invoice.director),
        selectinload(Invoice.finance),
        selectinload(Invoice.attachments),
    )


def _invoice_options_light() -> tuple:
    """Eager loading SO do essencial pra renderizar uma linha de listagem
    (criador + responsaveis). approval_history e attachments ficam de fora
    porque sao os caros — em /invoices/?per_page=100 disparam 2*100 sub-rows.
    """
    return (
        selectinload(Invoice.created_by).selectinload(User.department_obj),
        selectinload(Invoice.manager),
        selectinload(Invoice.director),
        selectinload(Invoice.finance),
    )


def _get_invoice(db: Session, invoice_id: str) -> Invoice:
    invoice = (
        db.query(Invoice)
        .options(*_invoice_options())
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota nao encontrada")
    return invoice


def _can_view(invoice: Invoice, user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.EMPLOYEE:
        return invoice.created_by_id == user.id
    if user.role == UserRole.MANAGER:
        return invoice.manager_id == user.id or (
            invoice.created_by is not None and invoice.created_by.manager_id == user.id
        )
    if user.role == UserRole.DIRECTOR:
        return invoice.director_id == user.id or invoice.created_by_id == user.id
    if user.role == UserRole.FINANCE:
        return invoice.status in {InvoiceStatus.APROVADO, InvoiceStatus.PAGO}
    if user.role == UserRole.CONTAS_A_PAGAR:
        return True
    return False


def _query_visible_invoices(db: Session, user: User, *, light: bool = False):
    options = _invoice_options_light() if light else _invoice_options()
    query = db.query(Invoice).options(*options)
    if user.role == UserRole.ADMIN:
        return query
    if user.role == UserRole.EMPLOYEE:
        return query.filter(Invoice.created_by_id == user.id)
    if user.role == UserRole.MANAGER:
        return query.filter(Invoice.manager_id == user.id)
    if user.role == UserRole.DIRECTOR:
        return query.filter(
            (Invoice.director_id == user.id) | (Invoice.created_by_id == user.id)
        )
    if user.role == UserRole.FINANCE:
        return query.filter(Invoice.status.in_([InvoiceStatus.APROVADO, InvoiceStatus.PAGO]))
    if user.role == UserRole.CONTAS_A_PAGAR:
        return query
    return query.filter(False)


def _status_from_filter(status_filter: str | None) -> InvoiceStatus | None:
    if not status_filter:
        return None
    try:
        return InvoiceStatus(status_filter)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filtro de status invalido.",
        ) from exc


def _unaccent_or_lower(col):
    """Em Postgres usa unaccent() pra busca acento-insensivel; em SQLite
    cai em lower() simples."""
    from app.database import engine
    from sqlalchemy import func as _func
    if engine.dialect.name == "postgresql":
        return _func.unaccent(_func.lower(col))
    return _func.lower(col)


def get_invoice_or_403(db: Session, invoice_id: str, user: User) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if not _can_view(invoice, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    return invoice


def get_invoices_for_user(
    db: Session,
    user: User,
    status_filter: str | None = None,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    created_by: str | None = None,
    supplier: str | None = None,
    department_id: str | None = None,
    light: bool = False,
) -> tuple[list[Invoice], int, float]:
    """Retorna (items_paginados, total_geral, soma_valor_total).

    A soma considera TODOS os itens que batem nos filtros, nao so da pagina
    atual — usada para exibir o totalizer no frontend.
    """
    from sqlalchemy import func, or_

    query = _query_visible_invoices(db, user, light=light)
    invoice_status = _status_from_filter(status_filter)
    if invoice_status:
        query = query.filter(Invoice.status == invoice_status)

    # Busca livre — agora cobre numero, descricao e fornecedor (acento-insensivel em PG)
    if search:
        term_raw = search.strip()
        like_unaccent = f"%{term_raw.lower()}%"
        digits = "".join(c for c in term_raw if c.isdigit())
        clauses = [
            _unaccent_or_lower(Invoice.invoice_number).like(like_unaccent),
            _unaccent_or_lower(Invoice.description).like(like_unaccent),
            _unaccent_or_lower(Invoice.supplier_name).like(like_unaccent),
            _unaccent_or_lower(Invoice.supplier_legal_name).like(like_unaccent),
        ]
        if digits and len(digits) >= 3:
            clauses.append(Invoice.supplier_document.ilike(f"%{digits}%"))
        query = query.filter(or_(*clauses))

    if supplier:
        sup_raw = supplier.strip()
        sup_like = f"%{sup_raw.lower()}%"
        digits = "".join(c for c in sup_raw if c.isdigit())
        sup_clauses = [
            _unaccent_or_lower(Invoice.supplier_name).like(sup_like),
            _unaccent_or_lower(Invoice.supplier_legal_name).like(sup_like),
        ]
        if digits and len(digits) >= 3:
            sup_clauses.append(Invoice.supplier_document.ilike(f"%{digits}%"))
        query = query.filter(or_(*sup_clauses))

    if department_id:
        query = query.join(User, Invoice.created_by_id == User.id).filter(
            User.department_id == department_id
        )

    if from_date:
        query = query.filter(Invoice.issue_date >= from_date)
    if to_date:
        query = query.filter(Invoice.issue_date <= to_date)
    if due_from:
        query = query.filter(Invoice.due_date >= due_from)
    if due_to:
        query = query.filter(Invoice.due_date <= due_to)

    if min_amount is not None:
        query = query.filter(Invoice.amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Invoice.amount <= max_amount)

    if created_by:
        creator_term = f"%{created_by.strip()}%"
        query = query.join(User, Invoice.created_by_id == User.id).filter(
            User.name.ilike(creator_term)
        )

    total = query.count()
    total_amount = float(
        db.query(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(Invoice.id.in_(query.with_entities(Invoice.id)))
        .scalar() or 0
    )
    items = (
        query.order_by(Invoice.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total, total_amount
