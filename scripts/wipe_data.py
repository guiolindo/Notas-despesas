"""Wipe completo dos dados de teste, preservando o admin principal.

Como usar
---------
Conecte-se ao banco que voce quer limpar (DATABASE_URL aponta pra ele) e:

    python -m scripts.wipe_data

O script:
  1. Confirma com voce qual admin sera preservado (o mais antigo por
     created_at e que ainda esta ativo).
  2. Pede confirmacao escrita ('SIM, LIMPAR TUDO').
  3. Apaga em ordem segura respeitando FKs:
     - audit_logs, approval_history, invoice_attachments, invoices
     - pending_admin_actions, password_reset_codes, cnpj_cache
     - director_departments, departments
     - users (exceto o admin preservado)
  4. Reseta os campos do admin: login_attempts=0, blocked_until=None,
     must_change_password=False, password_changed_at=now (invalida tokens
     antigos por seguranca).

NAO MEXE em:
  - smtp_settings (esta tabela nao e mais lida — config vive no .env)
  - usuario admin preservado (apenas reseta estado de sessao)
  - schema/migrations

Para producao no Railway: rode via 'railway run python -m scripts.wipe_data'
ou abra o servico web shell.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import (
    ApprovalHistory,
    AuditLog,
    CnpjCache,
    Department,
    Invoice,
    InvoiceAttachment,
    PasswordResetCode,
    PendingAdminAction,
    User,
    UserRole,
)


def main() -> int:
    # Garante que as migrations estao aplicadas — sem isso, contagens
    # podem falhar contra schema antigo (ex: coluna executed_by_id ausente).
    from app.main import _run_schema_migrations
    _run_schema_migrations()

    with SessionLocal() as session:
        # 1) Identifica admin a preservar
        admin = (
            session.query(User)
            .filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
            .order_by(User.created_at.asc())
            .first()
        )
        if not admin:
            print("Nenhum admin ativo encontrado. Aborto pra nao deixar o sistema sem acesso.")
            return 1

        print(
            f"Admin que sera PRESERVADO: {admin.name} <{admin.email}>"
            f"  (id={admin.id[:8]}..., criado em {admin.created_at})"
        )

        # 2) Resumo do que vai sumir
        counters = {
            "audit_logs":            session.query(AuditLog).count(),
            "approval_history":      session.query(ApprovalHistory).count(),
            "invoice_attachments":   session.query(InvoiceAttachment).count(),
            "invoices":              session.query(Invoice).count(),
            "pending_admin_actions": session.query(PendingAdminAction).count(),
            "password_reset_codes":  session.query(PasswordResetCode).count(),
            "cnpj_cache":            session.query(CnpjCache).count(),
            "departments":           session.query(Department).count(),
            "users (exceto admin)":  session.query(User).filter(User.id != admin.id).count(),
        }
        print("\nLinhas que serao APAGADAS:")
        for k, v in counters.items():
            print(f"  {k:30s} {v:>6d}")

        # 3) Confirmacao escrita
        ans = input("\nDigite exatamente 'SIM, LIMPAR TUDO' para confirmar: ").strip()
        if ans != "SIM, LIMPAR TUDO":
            print("Cancelado. Nada foi alterado.")
            return 0

        # 4) Apaga em ordem segura
        print("\nLimpando...")
        # M2M e tabelas dependentes primeiro
        session.execute(
            __import__("sqlalchemy").text("DELETE FROM director_departments")
        )
        session.query(InvoiceAttachment).delete(synchronize_session=False)
        session.query(ApprovalHistory).delete(synchronize_session=False)
        session.query(Invoice).delete(synchronize_session=False)
        session.query(PendingAdminAction).delete(synchronize_session=False)
        session.query(PasswordResetCode).delete(synchronize_session=False)
        session.query(CnpjCache).delete(synchronize_session=False)
        session.query(AuditLog).delete(synchronize_session=False)
        # Department referencia diretores; agora pode ir
        session.query(Department).delete(synchronize_session=False)
        # Users por ultimo, exceto o admin
        session.query(User).filter(User.id != admin.id).delete(synchronize_session=False)

        # 5) Normaliza estado do admin
        admin.login_attempts = 0
        admin.blocked_until = None
        admin.must_change_password = False
        admin.department_id = None
        admin.manager_id = None
        admin.password_changed_at = datetime.now(timezone.utc)
        admin.unavailable_for_notes = False

        session.commit()

    print("\nLimpeza concluida. Banco zerado, admin preservado.")
    print("Tokens emitidos antes deste momento foram invalidados (password_changed_at).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
