import warnings

from pydantic_settings import BaseSettings

_INSECURE_DEFAULT_KEY = "troque-em-producao-minimo-64-chars-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./economart.db"
    SECRET_KEY: str = _INSECURE_DEFAULT_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    MASTER_ENCRYPTION_KEY: str = ""
    # Cloudflare R2 (S3-compatible object storage)
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_ENDPOINT_URL: str = ""
    R2_BUCKET_NAME: str = ""
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_BLOCK_MINUTES: int = 10
    ENVIRONMENT: str = "DEV"

    # ─── Email — agora exclusivamente via env (admin do app nao mexe) ───
    # Esta separacao garante que um admin malicioso da aplicacao nao
    # consiga redirecionar SMTP para interceptar codigos de reset de senha
    # de outros admins/diretores. A configuracao SMTP fica em quem tem
    # acesso ao Railway, nao em quem tem login no app.
    EMAIL_PROVIDER: str = "SMTP"            # SMTP | RESEND | DISABLED
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USE_TLS: bool = True               # True=STARTTLS na porta 587, False=SSL na 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""                  # em texto puro no .env (acesso restrito)
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "Economart"
    RESEND_API_KEY: str = ""                # alternativa HTTP API (funciona em Railway Hobby)

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()


class InsecureSecretsError(RuntimeError):
    """Subida do app interrompida porque secrets criticos nao foram
    configurados em PROD. Capturada em app.main para apresentar uma tela
    HTTP estetica em vez de stacktrace cru no log do orquestrador."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "Configuracao incompleta em PROD: " + ", ".join(missing)
        )


def _collect_insecure_secrets() -> list[str]:
    """Retorna lista (rotulos) dos secrets que estao inseguros. Vazia se ok."""
    missing: list[str] = []
    if settings.SECRET_KEY == _INSECURE_DEFAULT_KEY or len(settings.SECRET_KEY) < 32:
        missing.append("SECRET_KEY")
    if not settings.MASTER_ENCRYPTION_KEY:
        missing.append("MASTER_ENCRYPTION_KEY")
    return missing


# Validacao de seguranca na inicializacao.
# P1-2 da auditoria: antes apenas warnings.warn em PROD; producao subia
# insegura. Agora:
#   - DEV: warning amigavel (continua subindo, util pra desenvolvedor).
#   - PROD: NAO levanta excecao aqui (precisariamos quebrar import). Em vez
#     disso, app.main consulta startup_security_failure() e monta uma
#     resposta HTTP estetica em qualquer rota, alem de logar com banner.
_IS_PROD = settings.ENVIRONMENT.upper() == "PROD"
_missing_secrets = _collect_insecure_secrets()


def startup_security_failure() -> InsecureSecretsError | None:
    """None se tudo ok. Senao retorna a excecao que main.py usa pra
    bloquear o app com tela amigavel."""
    if _IS_PROD and _missing_secrets:
        return InsecureSecretsError(_missing_secrets)
    return None


# Em DEV continua sendo warning informativo, nao bloqueia.
if not _IS_PROD and _missing_secrets:
    if "SECRET_KEY" in _missing_secrets:
        warnings.warn(
            "\n[SEGURANCA-DEV] SECRET_KEY esta com valor padrao ou curto demais.\n"
            "Defina SECRET_KEY no .env com chave aleatoria de 64+ chars.\n"
            "Exemplo: python -c \"import secrets; print(secrets.token_hex(64))\"",
            stacklevel=2,
        )
    if "MASTER_ENCRYPTION_KEY" in _missing_secrets:
        warnings.warn(
            "\n[SEGURANCA-DEV] MASTER_ENCRYPTION_KEY nao definida — PDFs nao "
            "serao criptografados nesta instancia local.",
            stacklevel=2,
        )
