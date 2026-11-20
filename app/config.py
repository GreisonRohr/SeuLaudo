import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DADOS_DIR = Path(os.getenv("SEULAUDO_DADOS", BASE_DIR / "dados"))
UPLOAD_DIR = DADOS_DIR / "laudos"
DB_PATH = DADOS_DIR / "seulaudo.db"

ANALITOS_PATH = BASE_DIR / "data" / "analitos.csv"
CRITICOS_PATH = BASE_DIR / "data" / "valores_criticos.csv"

# Claude
CLAUDE_MODEL = os.getenv("SEULAUDO_CLAUDE_MODEL", "claude-opus-5-5")
EFFORT_LEITURA = os.getenv("SEULAUDO_EFFORT_LEITURA", "high")
EFFORT_INTERPRETACAO = os.getenv("SEULAUDO_EFFORT_INTERPRETACAO", "high")

# Acesso: se SEULAUDO_SENHA estiver definida, o site pede usuário e senha (HTTP Basic)
USUARIO = os.getenv("SEULAUDO_USUARIO", "seulaudo")
SENHA = os.getenv("SEULAUDO_SENHA", "")

for d in (DADOS_DIR, UPLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)
