# Economart — Sistema de Aprovação de Notas Fiscais

Sistema web para gestão e aprovação de notas fiscais com fluxo de aprovação multinível, armazenamento criptografado de PDFs e geração de comprovantes com QR Code.

---

## Início rápido

**Windows:** dê duplo clique em `iniciar.bat` (na pasta `ECONOMART/`).

O script cria o ambiente, instala dependências, inicializa o banco e abre o navegador automaticamente em `http://localhost:7145`.

---

## Instalação manual

### Requisitos
- Python 3.12 ou superior (testado com Python 3.14)
- Conexão com internet para instalar pacotes na primeira execução

### Passos

```bash
# 1. Entre na pasta do projeto
cd economart_notas

# 2. (Opcional) Crie e ative um ambiente virtual
python -m venv venv
venv\Scripts\activate      # Windows
source venv/bin/activate   # Linux/macOS

# 3. Instale as dependências
pip install -r requirements.txt --prefer-binary

# 4. Configure o ambiente
copy .env.example .env     # Windows
cp .env.example .env       # Linux/macOS

# Gere as chaves de segurança e cole no .env:
python generate_keys.py

# 5. Inicialize o banco de dados
python init_db.py

# 6. Inicie o servidor
python -m uvicorn app.main:app --host 0.0.0.0 --port 7145
```

Acesse em `http://localhost:7145`.

---

## Configuração (.env)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | ✅ | Chave JWT (mín. 64 chars). Use `python generate_keys.py` |
| `MASTER_ENCRYPTION_KEY` | ✅ | Chave Fernet para criptografar PDFs. Use `python generate_keys.py` |
| `DATABASE_URL` | — | SQLite padrão: `sqlite:///./economart.db` |
| `GOOGLE_DRIVE_CREDENTIALS_PATH` | — | Caminho para o JSON da service account |
| `GOOGLE_DRIVE_FOLDER_ID` | — | ID da pasta no Drive para armazenar PDFs |
| `ENVIRONMENT` | — | `DEV` cria usuários de teste. Use `PRODUCTION` em produção |

---

## Usuários criados automaticamente (ENVIRONMENT=DEV)

| Usuário | Email | Senha |
|---|---|---|
| Administrador | admin@economart.com | Admin@2024! |
| Gestor | gestor@economart.com | Dev@2024! |
| Funcionário | funcionario@economart.com | Dev@2024! |
| Diretor | diretor@economart.com | Dev@2024! |
| Financeiro | financeiro@economart.com | Dev@2024! |

> ⚠️ Troque todas as senhas após o primeiro acesso.

---

## Perfis de acesso

| Perfil | Permissões |
|---|---|
| **EMPLOYEE** | Criar, editar e enviar notas fiscais |
| **MANAGER** | Aprovar ou reprovar notas (1ª etapa) |
| **DIRECTOR** | Aprovar ou reprovar notas (2ª etapa) |
| **FINANCE** | Visualizar aprovadas, imprimir comprovante, marcar como pago |
| **ADMIN** | Gerenciar usuários, visualizar logs de auditoria |

---

## Fluxo de aprovação

```
RASCUNHO → AGUARDANDO_GESTOR → AGUARDANDO_DIRETOR → APROVADO → PAGO
                ↓                       ↓
        REPROVADO_GESTOR        REPROVADO_DIRETOR
```

Gestores com perfil MANAGER também podem submeter diretamente ao diretor.

---

## Google Drive (opcional)

Se `GOOGLE_DRIVE_CREDENTIALS_PATH` não for configurado, os PDFs ficam em `uploads/` localmente (criptografados com AES-256).

Para ativar o Drive:
1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com)
2. Ative a **Google Drive API**
3. Crie uma **Service Account** e baixe o JSON de credenciais
4. Crie uma pasta no Drive e compartilhe com o e-mail da service account
5. Configure `GOOGLE_DRIVE_CREDENTIALS_PATH` e `GOOGLE_DRIVE_FOLDER_ID` no `.env`

---

## Verificação de notas (QR Code)

Cada comprovante impresso contém um QR Code que aponta para:
```
http://SEU_SERVIDOR:7145/verify/{id}
```
Esta rota é pública e exibe o status e a autenticidade da nota sem necessidade de login.

---

## Estrutura do projeto

```
economart_notas/
├── app/
│   ├── main.py              # Ponto de entrada FastAPI
│   ├── config.py            # Configurações via .env
│   ├── database.py          # Conexão SQLAlchemy
│   ├── models/              # Modelos ORM
│   ├── routers/             # Rotas da API e páginas
│   ├── services/            # Lógica de negócio
│   ├── security/            # JWT, hashing, dependências
│   ├── middleware/          # Rate limit, headers de segurança
│   ├── schemas/             # Schemas Pydantic
│   ├── templates/           # Templates Jinja2
│   └── static/              # CSS, JS, imagens
├── init_db.py               # Inicialização do banco e usuários
├── generate_keys.py         # Geração de chaves seguras
├── requirements.txt
└── .env.example
```
