@echo off
chcp 65001 >nul
echo ============================================================
echo  Economart — Geracao de Certificado TLS/HTTPS Local
echo  LGPD Art. 46 — Criptografia em Transito (rede interna)
echo ============================================================
echo.

REM Verifica se Python esta disponivel
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH.
    pause
    exit /b 1
)

REM Verifica se o pacote cryptography esta instalado
python -c "from cryptography import x509" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Instalando dependencia cryptography...
    pip install cryptography
)

REM Gera o certificado via Python
python -c "
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import datetime, ipaddress, socket

hostname = socket.gethostname()
try:
    local_ip = socket.gethostbyname(hostname)
except Exception:
    local_ip = '127.0.0.1'

print(f'[INFO] Gerando certificado para hostname: {hostname} / IP: {local_ip}')

key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend(),
)

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, 'BR'),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Economart Atacadista'),
    x509.NameAttribute(NameOID.COMMON_NAME, hostname),
])

san = x509.SubjectAlternativeName([
    x509.DNSName('localhost'),
    x509.DNSName(hostname),
    x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')),
    x509.IPAddress(ipaddress.IPv4Address(local_ip)),
])

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
    .add_extension(san, critical=False)
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .sign(key, hashes.SHA256(), default_backend())
)

with open('cert.pem', 'wb') as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

with open('key.pem', 'wb') as f:
    f.write(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))

print('[OK] Arquivos gerados: cert.pem e key.pem')
print('[OK] Validade: 825 dias')
print()
print('Para iniciar com HTTPS, use:')
print('  uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile key.pem --ssl-certfile cert.pem')
print()
print('IMPORTANTE: Adicione cert.pem como CA confiavel nos navegadores')
print('dos colaboradores para evitar avisos de seguranca.')
print()
print('No Windows: duplo-clique em cert.pem -> Instalar certificado')
print('           -> Repositorio: Autoridades de Certificacao Raiz Confiaveis')
"

if errorlevel 1 (
    echo [ERRO] Falha ao gerar certificado.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Pronto! Certificado gerado com sucesso.
echo  Arquivos: cert.pem e key.pem (neste diretorio)
echo ============================================================
echo.
pause
