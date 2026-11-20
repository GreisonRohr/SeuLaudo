"""Catálogo de analitos: padroniza nomes entre laboratórios e aplica os valores críticos.

O código padronizado permite juntar no histórico a "Glicemia de jejum" de um laboratório
com a "Glicose" de outro.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from . import config
from .models import Resultado
from .valores import normalizar, unidade

SCORE_MINIMO = 90


@dataclass
class Analito:
    codigo: str
    nome: str
    categoria: str
    descricao: str
    sinonimos: list[str] = field(default_factory=list)


@dataclass
class RegraCritica:
    codigo: str
    unidades: list[str]
    minimo: float | None
    maximo: float | None
    mensagem: str


def _ler_csv(caminho: Path) -> list[dict]:
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _num(s: str) -> float | None:
    return float(s) if s and s.strip() else None


class Catalogo:
    def __init__(self, analitos: list[Analito], regras: list[RegraCritica]):
        self.analitos = {a.codigo: a for a in analitos}
        self.regras = regras
        self._indice: dict[str, str] = {}
        for a in analitos:
            for nome in [a.nome, a.codigo, *a.sinonimos]:
                n = normalizar(nome)
                if n:
                    self._indice.setdefault(n, a.codigo)

    @classmethod
    def carregar(cls, analitos_path: Path | None = None, criticos_path: Path | None = None) -> "Catalogo":
        analitos = [
            Analito(
                codigo=r["codigo"].strip(),
                nome=r["nome"].strip(),
                categoria=r["categoria"].strip(),
                descricao=r["descricao"].strip(),
                sinonimos=[s.strip() for s in (r["sinonimos"] or "").split("|") if s.strip()],
            )
            for r in _ler_csv(analitos_path or config.ANALITOS_PATH)
        ]
        regras = [
            RegraCritica(
                codigo=r["codigo"].strip(),
                unidades=[u.strip() for u in (r["unidades"] or "").split("|") if u.strip()],
                minimo=_num(r["minimo"]),
                maximo=_num(r["maximo"]),
                mensagem=r["mensagem"].strip(),
            )
            for r in _ler_csv(criticos_path or config.CRITICOS_PATH)
        ]
        return cls(analitos, regras)

    def identificar(self, nome: str) -> Analito | None:
        n = normalizar(nome)
        if not n:
            return None
        if n in self._indice:
            return self.analitos[self._indice[n]]
        achado = process.extractOne(n, list(self._indice), scorer=fuzz.ratio)
        if achado and achado[1] >= SCORE_MINIMO:
            return self.analitos[self._indice[achado[0]]]
        return None

    def padronizar(self, r: Resultado) -> Resultado:
        a = self.identificar(r.analito) or (self.identificar(r.exame) if not r.analito else None)
        r.codigo, r.nome_padrao = (a.codigo, a.nome) if a else ("", "")
        self.verificar_critico(r)
        return r

    def verificar_critico(self, r: Resultado) -> Resultado:
        r.critico, r.mensagem_critica = False, ""
        if not r.codigo or r.valor_numerico is None:
            return r
        u = unidade(r.unidade)
        for regra in self.regras:
            if regra.codigo != r.codigo or (regra.unidades and u not in regra.unidades):
                continue
            v = r.valor_numerico
            if (regra.minimo is not None and v < regra.minimo) or (regra.maximo is not None and v > regra.maximo):
                r.critico, r.mensagem_critica = True, regra.mensagem
                break
        return r

    def descricao(self, codigo: str) -> str:
        a = self.analitos.get(codigo)
        return a.descricao if a else ""
