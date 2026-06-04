# Guia rápido — como rodar o sistema

Este guia mostra como instalar o Economart na sua máquina, configurar
o ambiente mínimo e logar pela primeira vez. Não exige conhecimento
prévio de FastAPI ou Python avançado.

## Pré-requisitos

- **Python 3.12 ou superior**. Para conferir: abra um terminal e rode
  `python --version`. Se aparecer uma versão menor, baixe em
  [python.org](https://www.python.org/downloads/).
- **Git**. Para clonar o repositório.
- **Sistema operacional**: Windows, Linux ou macOS. Os exemplos abaixo
  funcionam em qualquer um.
- **Editor de texto** para mexer no `.env` (VS Code, Notepad, qualquer
  editor que abra texto puro).

Banco de dados: **não precisa instalar Postgres** para desenvolvimento.
O sistema usa SQLite local por padrão (arquivo `economart.db` na pasta
do projeto). Em produção, o backend troca para Postgres automaticamente
quando a variável `DATABASE_URL` aponta pra ele.

---

## Passo a passo

### 1. Clonar o repositório

```bash
git clone https://github.com/guiolindo/Notas-despesas.git
cd Notas-despesas
```

### 2. Criar ambiente virtual

Ambiente virtual isola as bibliotecas do projeto do resto do seu
computador — evita conflitos com outros projetos Python.

**Windows (PowerShell)**:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Windows (Git Bash / cmd)**:
```cmd
python -m venv venv
venv\Scripts\activate
```

**Linux / macOS**:
```bash
python -m venv venv
source venv/bin/activate
```

Após ativar, o prompt mostra `(venv)` no início — isso confirma que
você está usando o ambiente isolado.

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

Demora 1-3 minutos na primeira vez. As bibliotecas principais são:

- **FastAPI** — framework web
- **SQLAlchemy** — acesso ao banco
- **bcrypt** — hash de senhas
- **cryptography** — criptografia de PDFs e tokens
- **boto3** — cliente do Cloudflare R2
- **Jinja2** — templates HTML
- **pypdf / reportlab** — leitura e geração de PDFs

### 4. Configurar variáveis de ambiente

Copie o arquivo de exemplo e edite com seus valores:

```bash
# Linux/macOS
cp .env.example .env

# Windows
copy .env.example .env
```

Abra o `.env` no seu editor e ajuste pelo menos estas chaves:

```ini
# Ambiente: DEV (desenvolvimento local) ou PROD (produção)
ENVIRONMENT=DEV

# Chave secreta — gere com:
#   python -c "import secrets; print(secrets.token_hex(64))"
SECRET_KEY=cole-aqui-a-string-gerada

# Chave mestra para criptografar PDFs — gere com:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
MASTER_ENCRYPTION_KEY=cole-aqui-a-fernet-key
```

Em DEV essas chaves podem ser quaisquer strings aleatórias. Em PROD,
o sistema **não sobe** se elas estiverem vazias ou usando o valor padrão
inseguro — uma tela 503 é mostrada até serem configuradas (medida de
segurança).

As outras variáveis (`DATABASE_URL`, `R2_*`, `SMTP_*`, `RESEND_API_KEY`)
podem ficar em branco para teste local. O sistema cai em modo
"sem persistência externa": SQLite local em vez de Postgres, anexos em
`uploads/` em vez de R2, sem emails (apenas log no terminal).

### 5. Subir o servidor

```bash
uvicorn app.main:app --reload
```

Aguarde aparecer:

```
Uvicorn running on http://127.0.0.1:8000
```

Pronto. Abra o navegador em `http://localhost:8000`.

### 6. Primeiro login

O sistema cria automaticamente um usuário administrador no primeiro
boot quando o banco está vazio:

- **Email**: `admin@economart.com`
- **Senha**: `Admin@2024!`

Ao logar pela primeira vez, o sistema **obriga** a troca de senha
(o backend devolve HTTP 428 em qualquer rota até você trocar).

⚠️ **Em produção, troque esta senha imediatamente**. O hash padrão está
documentado neste arquivo — qualquer pessoa que clonar o repo conhece.

---

## Erros comuns na instalação

### "python não é reconhecido"
No Windows, durante a instalação do Python marque "Add Python to PATH".
Se já instalou sem marcar, reinstale ou ajuste o PATH manualmente.

### "ModuleNotFoundError: No module named 'app'"
Você está rodando o `uvicorn` de fora da pasta do projeto. Faça `cd`
para a pasta `Notas-despesas` antes.

### "ERROR: Could not install bcrypt"
No Windows pode faltar o compilador C++. Instale o
[Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
ou use uma versão pré-compilada com `pip install bcrypt --only-binary :all:`.

### "OperationalError: unable to open database file"
A pasta atual não tem permissão de escrita. Mova o projeto para um
diretório seu (não dentro de `Program Files`, por exemplo) ou ajuste
`DATABASE_URL` para apontar para outro local.

### Tela 503 "Configuração de segurança incompleta"
O `SECRET_KEY` ou `MASTER_ENCRYPTION_KEY` está vazio ou usando o valor
padrão inseguro **e** o `ENVIRONMENT=PROD`. Em DEV isso não bloqueia
— se você está testando localmente, garanta `ENVIRONMENT=DEV` no `.env`.

### Tela em branco e botões "morrem" após reload
Limpe o `localStorage` e `sessionStorage` do navegador (F12 → Application
→ Storage → Clear) e refaça o login. Esse problema acontece quando o
navegador guardou estado de uma versão anterior do sistema.

---

## Rodando os testes

O projeto tem suite pytest automatizada cobrindo os fluxos críticos
de autenticação, fila de aprovação, rate-limit, health checks e fila
de email.

```bash
pip install pytest
python -m pytest tests/ -q
```

Esperado: 21 testes verdes em ~12 segundos.

Para detalhes ver [testing.md](testing.md).

---

## Próximos passos

- Para entender o **fluxo de aprovação** e os papéis: [domain-model.md](domain-model.md)
- Para entender **como funciona a autenticação e a criptografia**: [security.md](security.md)
- Para entender o **schema do banco**: [database.md](database.md)
- Para detalhes de **deploy em produção**: [operations.md](operations.md)
- Para entender o **frontend**: [frontend.md](frontend.md)
- Para a **referência dos endpoints**: [api-reference.md](api-reference.md)
