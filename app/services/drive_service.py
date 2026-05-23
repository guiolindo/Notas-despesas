import base64
import io
import logging
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import settings


logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
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
    def __init__(self) -> None:
        self._drive_client = None
        self._fallback_warned = False

    @property
    def credentials_path(self) -> Path:
        path = Path(settings.GOOGLE_DRIVE_CREDENTIALS_PATH)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def fallback_local(self) -> bool:
        return not settings.GOOGLE_DRIVE_FOLDER_ID or not self.credentials_path.exists()

    def _warn_fallback(self) -> None:
        if not self._fallback_warned:
            logger.warning(
                "[DriveService] Modo fallback local ativo. Configure Google Drive para producao."
            )
            self._fallback_warned = True

    def _client(self):
        if self.fallback_local:
            self._warn_fallback()
            return None
        if self._drive_client is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=DRIVE_SCOPES,
            )
            self._drive_client = build("drive", "v3", credentials=credentials)
        return self._drive_client

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

        from googleapiclient.http import MediaIoBaseUpload

        metadata = {
            "name": f"{Path(original_filename).name}.enc",
            "parents": [settings.GOOGLE_DRIVE_FOLDER_ID],
        }
        media = MediaIoBaseUpload(
            io.BytesIO(encrypted_bytes),
            mimetype="application/octet-stream",
            resumable=False,
        )
        uploaded = (
            client.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        return uploaded["id"], encrypted_key_b64

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
                raise FileNotFoundError("Arquivo local invalido ou Google Drive nao configurado.")

            from googleapiclient.http import MediaIoBaseDownload

            request = client.files().get_media(fileId=drive_file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            encrypted_bytes = buffer.getvalue()

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
            raise FileNotFoundError("Google Drive nao configurado para remover arquivo remoto.")
        client.files().delete(fileId=drive_file_id).execute()

    def _local_file_path(self, drive_file_id: str) -> Path:
        local_id = drive_file_id.removeprefix("local:")
        if not local_id or "/" in local_id or "\\" in local_id or ".." in local_id:
            raise ValueError("Identificador local invalido.")
        return UPLOADS_DIR / f"{local_id}.enc"


drive_service = DriveService()
