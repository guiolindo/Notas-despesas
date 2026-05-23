import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Tabela associativa diretor <-> departamento (many-to-many)
director_departments = Table(
    "director_departments",
    Base.metadata,
    Column("director_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", String(36), ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)


class Department(Base):
    __tablename__ = "departments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(120), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    # Usuários pertencentes ao setor
    members = relationship("User", foreign_keys="User.department_id", back_populates="department_obj")

    # Diretores responsáveis pelo setor
    directors = relationship(
        "User",
        secondary=director_departments,
        back_populates="directed_departments",
    )
