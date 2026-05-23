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
    GOOGLE_DRIVE_CREDENTIALS_PATH: str = "credentials.json"
    GOOGLE_DRIVE_FOLDER_ID: str = ""
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_BLOCK_MINUTES: int = 10
    ENVIRONMENT: str = "DEV"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

# Validacao de segurança na inicializacao
if settings.SECRET_KEY == _INSECURE_DEFAULT_KEY:
    warnings.warn(
        "\n[SEGURANCA] SECRET_KEY esta com o valor padrao inseguro!\n"
        "Defina SECRET_KEY no arquivo .env com uma chave aleatoria de 64+ caracteres.\n"
        "Exemplo: python -c \"import secrets; print(secrets.token_hex(64))\"",
        stacklevel=2,
    )

if settings.ENVIRONMENT.upper() == "PROD" and not settings.MASTER_ENCRYPTION_KEY:
    warnings.warn(
        "\n[SEGURANCA] MASTER_ENCRYPTION_KEY nao definida em ambiente de producao!\n"
        "PDFs nao poderao ser criptografados com AES-256.",
        stacklevel=2,
    )
