"""Gera preview/index.html (página única para o claude.ai) a partir do template.

Embute o catálogo de analitos, os valores críticos, o laudo de exemplo e os mesmos prompts
do backend (app/extratores/claude.py e app/interpretacao.py), para a prévia não divergir do sistema.
"""
import csv
import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("SEULAUDO_DADOS", tempfile.mkdtemp(prefix="seulaudo-build-"))
from app.extratores.claude import SYSTEM as PROMPT_LEITURA  # noqa: E402
from app.interpretacao import SYSTEM as PROMPT_INTERP  # noqa: E402


def ler(nome, campos):
    with open(RAIZ / "data" / nome, encoding="utf-8") as f:
        return [[r[c] for c in campos] for r in csv.DictReader(f, delimiter=";")]


j = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
html = (RAIZ / "preview/template.html").read_text(encoding="utf-8")
for marca, valor in {
    "__ANALITOS__": ler("analitos.csv", ["codigo", "nome", "sinonimos", "categoria", "descricao"]),
    "__CRITICOS__": ler("valores_criticos.csv", ["codigo", "unidades", "minimo", "maximo", "mensagem"]),
    "__EXEMPLO__": (RAIZ / "exemplos/laudo_exemplo.txt").read_text(encoding="utf-8"),
    "__PROMPT_LEITURA__": PROMPT_LEITURA,
    "__PROMPT_INTERP__": PROMPT_INTERP,
}.items():
    html = html.replace(marca, j(valor).replace("</", "<\\/"))
(RAIZ / "preview/index.html").write_text(html, encoding="utf-8")
print(f"preview/index.html: {len(html)} bytes")
