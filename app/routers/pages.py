from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import templates
from app.models import User
from app.security.page_auth import require_page_login, require_page_role


router = APIRouter()


# ─── Paginas publicas ───────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html")


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request):
    return templates.TemplateResponse(request, "reset_password.html")


@router.get("/privacidade", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html")


@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/dashboard")


# ─── Paginas que apenas exigem login ────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    # dashboard.html ramifica layout por current_user.role (CONTAS_A_PAGAR
    # vs aprovadores), entao precisa do user no contexto.
    return templates.TemplateResponse(
        request, "dashboard.html", {"current_user": guard}
    )


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "change_password.html")


@router.get("/configuracoes", response_class=HTMLResponse)
def configuracoes_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "configuracoes.html")


@router.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(
        request, "faq.html", {"user_role": guard.role.value}
    )


@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "alerts.html")


@router.get("/invoices", response_class=HTMLResponse)
def invoices_list_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "invoices/list.html")


@router.get("/invoices/new", response_class=HTMLResponse)
def invoices_create_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "invoices/create.html")


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def invoices_detail_page(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "invoices/detail.html", {"invoice_id": invoice_id})


@router.get("/invoices/{invoice_id}/edit", response_class=HTMLResponse)
def invoices_edit_page(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    guard = require_page_login(request, db)
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "invoices/edit.html", {"invoice_id": invoice_id})


# ─── Paginas exclusivas para Gestores ───────────────────────────────────────

@router.get("/manager/queue", response_class=HTMLResponse)
def manager_queue_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "MANAGER", "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "manager/queue.html")


@router.get("/manager/invoices/{invoice_id}", response_class=HTMLResponse)
def manager_invoice_detail(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "MANAGER", "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "manager/invoice_detail.html", {"invoice_id": invoice_id})


# ─── Paginas exclusivas para Diretores ──────────────────────────────────────

@router.get("/director/queue", response_class=HTMLResponse)
def director_queue_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "DIRECTOR", "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "director/queue.html")


@router.get("/director/invoices/{invoice_id}", response_class=HTMLResponse)
def director_invoice_detail(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "DIRECTOR", "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "director/invoice_detail.html", {"invoice_id": invoice_id})


# ─── Paginas exclusivas para Financeiro ─────────────────────────────────────

@router.get("/finance/queue", response_class=HTMLResponse)
def finance_queue_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "FINANCE", "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "finance/queue.html")


@router.get("/finance/invoices/{invoice_id}", response_class=HTMLResponse)
def finance_invoice_detail(request: Request, invoice_id: str, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "FINANCE", "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "finance/invoice_detail.html", {"invoice_id": invoice_id})


# /finance/history removida — funcionalidade fundida em /invoices que agora
# tem totalizer + filtros completos (busca, vencimento, valor, criador).


# ─── Paginas exclusivas para Admin ──────────────────────────────────────────

@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "admin/users.html", {})


@router.get("/admin/users/new", response_class=HTMLResponse)
def admin_create_user_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "admin/user_form.html", {"mode": "create"})


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_edit_user_page(request: Request, user_id: str, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "admin/user_form.html", {"mode": "edit", "user_id": user_id})


@router.get("/admin/audit-logs", response_class=HTMLResponse)
def admin_audit_logs_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "admin/audit_logs.html", {})


@router.get("/admin/departments", response_class=HTMLResponse)
def admin_departments_page(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "ADMIN")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "admin/departments.html", {})


# ─── Paginas exclusivas para Contas a Pagar ─────────────────────────────────

@router.get("/contas-a-pagar/scanner", response_class=HTMLResponse)
def contas_a_pagar_scanner(request: Request, db: Session = Depends(get_db)):
    guard = require_page_role(request, db, "CONTAS_A_PAGAR", "ADMIN", "FINANCE")
    if not isinstance(guard, User):
        return guard
    return templates.TemplateResponse(request, "contas_a_pagar/scanner.html")


