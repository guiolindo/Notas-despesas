from contextlib import contextmanager

from sqlalchemy import inspect, text

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Department, User, UserRole
from app.security.hashing import hash_password


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _add_column_if_missing(table: str, column: str, definition: str) -> None:
    """Adiciona coluna ao SQLite se ainda não existir (migração não destrutiva)."""
    inspector = inspect(engine)
    existing = [c["name"] for c in inspector.get_columns(table)]
    if column not in existing:
        with engine.connect() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {definition}"))
            conn.commit()
        print(f"  Migração: adicionada coluna '{column}' em '{table}'")


def run_migrations() -> None:
    """Aplica migrações incrementais sem destruir dados existentes."""
    # Novas colunas em users
    _add_column_if_missing("users", "department_id", "department_id VARCHAR(36) REFERENCES departments(id)")
    _add_column_if_missing("users", "submit_directly_to_director", "submit_directly_to_director BOOLEAN NOT NULL DEFAULT 0")


def create_user_if_missing(
    db,
    *,
    name: str,
    email: str,
    password: str,
    role: UserRole,
    department_id: str | None = None,
    must_change_password: bool = False,
) -> User:
    user = db.query(User).filter(User.email == email).one_or_none()
    if user:
        if not user.hashed_password.startswith("$2"):
            user.hashed_password = hash_password(password)
        # Não sobrescreve must_change_password — respeita o que o usuário já fez
        return user

    user = User(
        name=name,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        department_id=department_id,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    return user


def create_department_if_missing(db, *, name: str, description: str | None = None) -> Department:
    dept = db.query(Department).filter(Department.name == name).one_or_none()
    if dept:
        return dept
    dept = Department(name=name, description=description)
    db.add(dept)
    db.flush()
    return dept


def create_dev_users(db) -> None:
    if settings.ENVIRONMENT not in {"DEV", "DEVELOPMENT", "LOCAL"}:
        return

    # Criar setores de exemplo
    mkt = create_department_if_missing(db, name="Marketing", description="Setor de marketing e comunicação")
    ops = create_department_if_missing(db, name="Operacoes", description="Setor de operações")
    fin = create_department_if_missing(db, name="Financeiro", description="Setor financeiro")

    manager = create_user_if_missing(
        db,
        name="Gestor DEV",
        email="gestor@economart.com",
        password="Dev@2024!",
        role=UserRole.MANAGER,
        department_id=ops.id,
    )
    employee = create_user_if_missing(
        db,
        name="Funcionario DEV",
        email="funcionario@economart.com",
        password="Dev@2024!",
        role=UserRole.EMPLOYEE,
        department_id=ops.id,
    )
    employee.manager_id = manager.id

    diretor = create_user_if_missing(
        db,
        name="Diretor DEV",
        email="diretor@economart.com",
        password="Dev@2024!",
        role=UserRole.DIRECTOR,
        department_id=None,
    )
    # Associar diretor aos setores
    for dept in [ops, mkt]:
        if dept not in diretor.directed_departments:
            diretor.directed_departments.append(dept)

    create_user_if_missing(
        db,
        name="Financeiro DEV",
        email="financeiro@economart.com",
        password="Dev@2024!",
        role=UserRole.FINANCE,
        department_id=fin.id,
    )


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    run_migrations()
    with session_scope() as db:
        create_user_if_missing(
            db,
            name="Administrador Economart",
            email="admin@economart.com",
            password="Admin@2024!",
            role=UserRole.ADMIN,
            must_change_password=True,
        )
        # create_dev_users(db)  # desabilitado — cria usuarios de teste (DEV)


if __name__ == "__main__":
    init_db()
    print(f"Banco inicializado em {settings.DATABASE_URL}")
