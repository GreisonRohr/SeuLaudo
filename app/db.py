"""Persistência em SQLite: perfis (paciente e familiares), laudos e histórico de resultados."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS perfis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    data_nascimento TEXT DEFAULT '',
    sexo TEXT DEFAULT '',
    criado_em TEXT NOT NULL,
    consentimento_em TEXT          -- aceite do termo de uso de dados de saúde (LGPD)
);
CREATE TABLE IF NOT EXISTS laudos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    perfil_id INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    arquivo_nome TEXT,
    arquivo_path TEXT,
    mime TEXT,
    extrator TEXT,
    status TEXT NOT NULL,          -- lido | conferido | interpretado | erro
    dados_json TEXT,
    interpretacao_json TEXT,
    erro TEXT
);
CREATE TABLE IF NOT EXISTS resultados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    laudo_id INTEGER NOT NULL REFERENCES laudos(id) ON DELETE CASCADE,
    perfil_id INTEGER NOT NULL REFERENCES perfis(id) ON DELETE CASCADE,
    codigo TEXT NOT NULL,
    nome TEXT,
    data_coleta TEXT,              -- AAAA-MM-DD, para ordenar
    valor TEXT,
    valor_numerico REAL,
    unidade TEXT,
    ref_min REAL,
    ref_max REAL,
    situacao TEXT
);
CREATE INDEX IF NOT EXISTS ix_resultados_perfil ON resultados (perfil_id, codigo, data_coleta);
"""


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def data_iso(data_br: str) -> str:
    """DD/MM/AAAA -> AAAA-MM-DD (vazio se inválida)."""
    try:
        return datetime.strptime((data_br or "").strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


@contextmanager
def conexao():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with conexao() as con:
        con.executescript(SCHEMA)


# ----------------------------------------------------------------- perfis
def criar_perfil(nome: str, data_nascimento: str = "", sexo: str = "", consentimento: bool = False) -> int:
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO perfis (nome, data_nascimento, sexo, criado_em, consentimento_em) VALUES (?,?,?,?,?)",
            (nome, data_nascimento, sexo, _agora(), _agora() if consentimento else None),
        )
        return cur.lastrowid


def listar_perfis() -> list[dict]:
    with conexao() as con:
        rows = con.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM laudos l WHERE l.perfil_id = p.id) AS qtd_laudos "
            "FROM perfis p ORDER BY p.id"
        ).fetchall()
    return [dict(r) for r in rows]


def obter_perfil(perfil_id: int) -> dict | None:
    with conexao() as con:
        row = con.execute("SELECT * FROM perfis WHERE id = ?", (perfil_id,)).fetchone()
        return dict(row) if row else None


def excluir_perfil(perfil_id: int) -> list[str]:
    """Apaga o perfil, seus laudos e resultados. Devolve os arquivos a remover do disco."""
    with conexao() as con:
        arquivos = [r["arquivo_path"] for r in con.execute(
            "SELECT arquivo_path FROM laudos WHERE perfil_id = ?", (perfil_id,)) if r["arquivo_path"]]
        con.execute("DELETE FROM perfis WHERE id = ?", (perfil_id,))
    return arquivos


# ----------------------------------------------------------------- laudos
def criar_laudo(perfil_id, arquivo_nome, arquivo_path, mime, extrator, status, dados=None, erro=None) -> int:
    with conexao() as con:
        cur = con.execute(
            """INSERT INTO laudos (perfil_id, criado_em, atualizado_em, arquivo_nome, arquivo_path, mime,
                                   extrator, status, dados_json, erro) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (perfil_id, _agora(), _agora(), arquivo_nome, arquivo_path, mime, extrator, status,
             json.dumps(dados, ensure_ascii=False) if dados is not None else None, erro),
        )
        return cur.lastrowid


def atualizar_laudo(laudo_id: int, **campos):
    for k in ("dados", "interpretacao"):
        if k in campos:
            v = campos.pop(k)
            campos[f"{k}_json"] = json.dumps(v, ensure_ascii=False) if v is not None else None
    campos["atualizado_em"] = _agora()
    sets = ", ".join(f"{k} = ?" for k in campos)
    with conexao() as con:
        con.execute(f"UPDATE laudos SET {sets} WHERE id = ?", (*campos.values(), laudo_id))


def _laudo(row) -> dict:
    d = dict(row)
    for k in ("dados_json", "interpretacao_json"):
        d[k.removesuffix("_json")] = json.loads(d.pop(k)) if d.get(k) else None
    return d


def obter_laudo(laudo_id: int) -> dict | None:
    with conexao() as con:
        row = con.execute("SELECT * FROM laudos WHERE id = ?", (laudo_id,)).fetchone()
        return _laudo(row) if row else None


def listar_laudos(perfil_id: int) -> list[dict]:
    with conexao() as con:
        rows = con.execute(
            "SELECT id, criado_em, arquivo_nome, extrator, status, erro, dados_json FROM laudos "
            "WHERE perfil_id = ? ORDER BY id DESC", (perfil_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        dados = json.loads(d.pop("dados_json")) if d.get("dados_json") else {}
        res = dados.get("resultados") or []
        d.update(
            laboratorio=dados.get("laboratorio", ""),
            data_coleta=dados.get("data_coleta", ""),
            tipo=dados.get("tipo", ""),
            titulo=dados.get("titulo_exame", ""),
            qtd_resultados=len(res),
            qtd_alterados=sum(1 for x in res if x.get("situacao") in ("alto", "baixo", "alterado")),
            qtd_criticos=sum(1 for x in res if x.get("critico")),
        )
        out.append(d)
    return out


def excluir_laudo(laudo_id: int) -> str | None:
    with conexao() as con:
        row = con.execute("SELECT arquivo_path FROM laudos WHERE id = ?", (laudo_id,)).fetchone()
        con.execute("DELETE FROM laudos WHERE id = ?", (laudo_id,))
    return row["arquivo_path"] if row else None


# --------------------------------------------------------------- histórico
def gravar_resultados(laudo_id: int, perfil_id: int, laudo: dict):
    data = data_iso(laudo.get("data_coleta", ""))
    with conexao() as con:
        con.execute("DELETE FROM resultados WHERE laudo_id = ?", (laudo_id,))
        con.executemany(
            """INSERT INTO resultados (laudo_id, perfil_id, codigo, nome, data_coleta, valor, valor_numerico,
                                       unidade, ref_min, ref_max, situacao) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [(laudo_id, perfil_id, r["codigo"], r.get("nome_padrao") or r.get("analito"), data, r.get("valor"),
              r.get("valor_numerico"), r.get("unidade"), r.get("ref_min"), r.get("ref_max"), r.get("situacao"))
             for r in laudo.get("resultados") or [] if r.get("codigo")],
        )


def historico(perfil_id: int, codigo: str | None = None, antes_do_laudo: int | None = None) -> list[dict]:
    sql = "SELECT r.*, l.criado_em FROM resultados r JOIN laudos l ON l.id = r.laudo_id WHERE r.perfil_id = ?"
    args: list = [perfil_id]
    if codigo:
        sql += " AND r.codigo = ?"
        args.append(codigo)
    if antes_do_laudo is not None:
        sql += " AND r.laudo_id != ?"
        args.append(antes_do_laudo)
    sql += " ORDER BY r.codigo, COALESCE(NULLIF(r.data_coleta, ''), substr(l.criado_em, 1, 10)), r.id"
    with conexao() as con:
        return [dict(r) for r in con.execute(sql, args)]


def remover_arquivo(caminho: str | None):
    if caminho:
        Path(caminho).unlink(missing_ok=True)
