import base64
import io
import logging
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import settings


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = PROJECT_ROOT / "uploads"


def generate_file_key() -> bytes:
    return Fernet.generate_key()


def encrypt_data(data: bytes, key: bytes) -> bytes:
    return Fernet(key).encrypt(data)


def decrypt_data(token: bytes, key: bytes) -> bytes:
    return Fernet(key).decrypt(token)


def _master_key() -> bytes:
    key = settings.MASTER_ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.strip().encode("utf-8")
    if not key:
        raise ValueError(
            "MASTER_ENCRYPTION_KEY nao configurada. Gere uma chave com python generate_keys.py."
        )
    Fernet(key)
    return key


def encrypt_key_with_master(file_key: bytes) -> str:
    encrypted = Fernet(_master_key()).encrypt(file_key)
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_key_with_master(encrypted_key_b64: str) -> bytes:
    encrypted = base64.urlsafe_b64decode(encrypted_key_b64.encode("ascii"))
    return Fernet(_master_key()).decrypt(encrypted)


class DriveService:
    """Storage service backed por Cloudflare R2 (S3-compatible).

    Mantem o nome historico DriveService para minimizar refactor no resto do app.
    Em desenvolvimento sem credenciais, faz fallback para uploads/ local.
    """

    def __init__(self) -> None:
        self._s3_client = None
        self._fallback_warned = False

    @property
    def _has_credentials(self) -> bool:
        return bool(
            settings.R2_ACCESS_KEY_ID
            and settings.R2_SECRET_ACCESS_KEY
            and settings.R2_ENDPOINT_URL
            and settings.R2_BUCKET_NAME
        )

    @property
    def fallback_local(self) -> bool:
        return not self._has_credentials

    def _warn_fallback(self) -> None:
        if not self._fallback_warned:
            logger.warning(
                "[DriveService] Modo fallback local ativo. Configure R2_* para producao."
            )
            self._fallback_warned = True

    def _client(self):
        if self.fallback_local:
            self._warn_fallback()
            return None
        if self._s3_client is None:
            import boto3
            from botocore.config import Config

            self._s3_client = boto3.client(
                "s3",
                endpoint_url=settings.R2_ENDPOINT_URL,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
                region_name="auto",
            )
        return self._s3_client

    def upload_encrypted_file(
        self,
        file_bytes: bytes,
        original_filename: str,
    ) -> tuple[str, str]:
        file_key = generate_file_key()
        encrypted_bytes = encrypt_data(file_bytes, file_key)
        encrypted_key_b64 = encrypt_key_with_master(file_key)

        client = self._client()
        if client is None:
            local_id = str(uuid.uuid4())
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            (UPLOADS_DIR / f"{local_id}.enc").write_bytes(encrypted_bytes)
            return f"local:{local_id}", encrypted_key_b64

        object_key = f"{uuid.uuid4()}.enc"
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=object_key,
            Body=encrypted_bytes,
            ContentType="application/octet-stream",
            Metadata={"original_filename": Path(original_filename).name[:200]},
        )
        return object_key, encrypted_key_b64

    def download_and_decrypt(
        self,
        drive_file_id: str,
        encrypted_key_b64: str,
    ) -> bytes:
        if drive_file_id.startswith("local:"):
            encrypted_bytes = self._local_file_path(drive_file_id).read_bytes()
        else:
            client = self._client()
            if client is None:
                raise FileNotFoundError("R2 nao configurado para baixar arquivo remoto.")
            response = client.get_object(Bucket=settings.R2_BUCKET_NAME, Key=drive_file_id)
            encrypted_bytes = response["Body"].read()

        file_key = decrypt_key_with_master(encrypted_key_b64)
        return decrypt_data(encrypted_bytes, file_key)

    def delete_file(self, drive_file_id: str) -> None:
        if drive_file_id.startswith("local:"):
            path = self._local_file_path(drive_file_id)
            if path.exists():
                path.unlink()
            return

        client = self._client()
        if client is None:
            raise FileNotFoundError("R2 nao configurado para remover arquivo remoto.")
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=drive_file_id)

    def _local_file_path(self, drive_file_id: str) -> Path:
        local_id = drive_file_id.removeprefix("local:")
        if not local_id or "/" in local_id or "\\" in local_id or ".." in local_id:
            raise ValueError("Identificador local invalido.")
        return UPLOADS_DIR / f"{local_id}.enc"


drive_service = DriveService()
