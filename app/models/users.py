import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    FINANCE = "FINANCE"


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    # 'department' (String) era a coluna antiga antes de virar FK. Removida do
    # modelo; a migration abaixo derruba do DB via _run_schema_migrations.
    manager_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_login = Column(DateTime, nullable=True)
    login_attempts = Column(Integer, default=0, nullable=False)
    blocked_until = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, default=False, nullable=False)
    # Marca o instante da ultima troca de senha. Tokens emitidos ANTES desse
    # timestamp sao considerados invalidos (forca relogin apos reset).
    password_changed_at = Column(DateTime, default=utc_now, nullable=True)

    # Setor ao qual o usuário pertence
    department_id = Column(String(36), ForeignKey("departments.id"), nullable=True)
    # Se True, o funcionário envia nota diretamente ao diretor (sem gestor)
    submit_directly_to_director = Column(Boolean, default=False, nullable=False)
    # Auto-pausa de recebimento (ex: ferias do diretor). Quando True, nao
    # aparece na lista de selecao de diretor para novas notas. Notas ja
    # atribuidas continuam visiveis e aprovaveis por ele.
    unavailable_for_notes = Column(Boolean, default=False, nullable=False)

    manager = relationship("User", remote_side=[id], backref="team_members")
    created_invoices = relationship(
        "Invoice",
        foreign_keys="Invoice.created_by_id",
        back_populates="created_by",
    )
    department_obj = relationship(
        "Department",
        foreign_keys=[department_id],
        back_populates="members",
    )
    directed_departments = relationship(
        "Department",
        secondary="director_departments",
        back_populates="directors",
    )
