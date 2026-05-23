import os
import warnings

from pydantic_settings import BaseSettings

# DEBUG temporario — verificar se env vars chegam no processo
print(f"[DEBUG-ENV] SECRET_KEY presente em os.environ: {('SECRET_KEY' in os.environ)}", flush=True)
print(f"[DEBUG-ENV] SECRET_KEY len: {len(os.environ.get('SECRET_KEY', ''))}", flush=True)
print(f"[DEBUG-ENV] DATABASE_URL prefix: {os.environ.get('DATABASE_URL', '')[:15]}", flush=True)
print(f"[DEBUG-ENV] ENVIRONMENT: {os.environ.get('ENVIRONMENT', 'NAO-DEFINIDO')}", flush=True)
print(f"[DEBUG-ENV] Total env vars: {len(os.environ)}", flush=True)
print(f"[DEBUG-ENV] TEST_VAR: {os.environ.get('TEST_VAR', 'AUSENTE')}", flush=True)
print(f"[DEBUG-ENV] RAILWAY_ENVIRONMENT: {os.environ.get('RAILWAY_ENVIRONMENT', 'AUSENTE')}", flush=True)
print(f"[DEBUG-ENV] RAILWAY_SERVICE_NAME: {os.environ.get('RAILWAY_SERVICE_NAME', 'AUSENTE')}", flush=True)
# Lista todas as variaveis que comecam com letra maiuscula (provavelmente do usuario)
_user_vars = sorted([k for k in os.environ.keys() if k[0].isupper() and not k.startswith(('PATH', 'HOME', 'LANG', 'TERM', 'PWD', 'SHLVL', 'PYTHON', 'GUNICORN'))])
print(f"[DEBUG-ENV] Var names (filtradas): {_user_vars}", flush=True)

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
    # Conteudo completo do JSON da conta de servico (usado no Railway em vez do arquivo)
    GOOGLE_CREDENTIALS_JSON: str = ""
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
