from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.main import templates


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    return templates.TemplateResponse(request, "change_password.html")


@router.get("/invoices", response_class=HTMLResponse)
def invoices_list_page(request: Request):
    return templates.TemplateResponse(request, "invoices/list.html")


@router.get("/invoices/new", response_class=HTMLResponse)
def invoices_create_page(request: Request):
    return templates.TemplateResponse(request, "invoices/create.html")


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def invoices_detail_page(request: Request, invoice_id: str):
    return templates.TemplateResponse(request, "invoices/detail.html", {"invoice_id": invoice_id})


@router.get("/invoices/{invoice_id}/edit", response_class=HTMLResponse)
def invoices_edit_page(request: Request, invoice_id: str):
    return templates.TemplateResponse(request, "invoices/edit.html", {"invoice_id": invoice_id})


@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request):
    return templates.TemplateResponse(request, "alerts.html")


@router.get("/manager/queue", response_class=HTMLResponse)
def manager_queue_page(request: Request):
    return templates.TemplateResponse(request, "manager/queue.html")


@router.get("/manager/invoices/{invoice_id}", response_class=HTMLResponse)
def manager_invoice_detail(request: Request, invoice_id: str):
    return templates.TemplateResponse(request, "manager/invoice_detail.html", {"invoice_id": invoice_id})


@router.get("/director/queue", response_class=HTMLResponse)
def director_queue_page(request: Request):
    return templates.TemplateResponse(request, "director/queue.html")


@router.get("/director/invoices/{invoice_id}", response_class=HTMLResponse)
def director_invoice_detail(request: Request, invoice_id: str):
    return templates.TemplateResponse(request, "director/invoice_detail.html", {"invoice_id": invoice_id})


@router.get("/finance/queue", response_class=HTMLResponse)
def finance_queue_page(request: Request):
    return templates.TemplateResponse(request, "finance/queue.html")


@router.get("/finance/invoices/{invoice_id}", response_class=HTMLResponse)
def finance_invoice_detail(request: Request, invoice_id: str):
    return templates.TemplateResponse(request, "finance/invoice_detail.html", {"invoice_id": invoice_id})


@router.get("/finance/history", response_class=HTMLResponse)
def finance_history_page(request: Request):
    return templates.TemplateResponse(request, "finance/history.html")


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    return templates.TemplateResponse(request, "admin/users.html", {})


@router.get("/admin/users/new", response_class=HTMLResponse)
def admin_create_user_page(request: Request):
    return templates.TemplateResponse(request, "admin/user_form.html", {"mode": "create"})


@router.get("/admin/users/{user_id}/edit", response_class=HTMLResponse)
def admin_edit_user_page(request: Request, user_id: str):
    return templates.TemplateResponse(request, "admin/user_form.html", {"mode": "edit", "user_id": user_id})


@router.get("/admin/audit-logs", response_class=HTMLResponse)
def admin_audit_logs_page(request: Request):
    return templates.TemplateResponse(request, "admin/audit_logs.html", {})


@router.get("/admin/departments", response_class=HTMLResponse)
def admin_departments_page(request: Request):
    return templates.TemplateResponse(request, "admin/departments.html", {})


@router.get("/privacidade", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html")


@router.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/dashboard")
