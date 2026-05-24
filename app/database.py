from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


def _build_engine():
    url = settings.DATABASE_URL
    # Railway entrega postgres:// mas SQLAlchemy 2.x exige postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    kwargs: dict = {"echo": False}
    if url.startswith("sqlite"):
        # check_same_thread só existe no SQLite (desenvolvimento local)
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL no Railway: o gateway derruba conexoes idle agressivamente
        # (causa 'SSL SYSCALL error: EOF detected' em requests apos pausa).
        # Combinacao para zerar isso:
        #  - pool_pre_ping: valida conexao antes de usar (descarta mortas)
        #  - pool_recycle 180s: forca renovacao antes do timeout do Railway
        #  - TCP keepalives: pacote keep-alive a cada 30s impede o middleware
        #    de marcar a conexao como ociosa
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 180
        kwargs["connect_args"] = {
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
            "connect_timeout": 10,
        }

    return create_engine(url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
