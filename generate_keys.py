"""Gera as chaves necessarias para o .env."""
import secrets

from cryptography.fernet import Fernet


print("# Cole estas linhas no seu .env:")
print(f"SECRET_KEY={secrets.token_hex(32)}")
print(f"MASTER_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
