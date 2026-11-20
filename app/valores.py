"""Leitura de valores e faixas de referência no formato brasileiro e classificação.

A classificação (normal / alto / baixo / alterado) é sempre feita aqui, por regra,
comparando o valor com a referência impressa no próprio laudo. A IA não decide isso.
"""
from __future__ import annotations

import re
import unicodedata

from .models import Resultado

_NUM = r"[-+]?\d+(?:[.,]\d+)*"


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    t = sem_acento(texto or "").lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def numero(texto: str) -> float | None:
    """Converte '1.234,5', '12,5', '250.000', '4.5' e '0,85' em float."""
    if texto is None:
        return None
    m = re.search(_NUM, str(texto))
    if not m:
        return None
    s = m.group(0).lstrip("+")
    if "," in s and "." in s:  # 1.234,56
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:  # 12,5 ou 1,234 (vírgula é decimal no Brasil)
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif s.count(".") > 1:  # 1.234.567
        s = s.replace(".", "")
    elif "." in s:
        inteiro, dec = s.split(".")
        # 250.000 / 4.500 = milhar; 4.5 / 0.85 / 13.50 = decimal
        if len(dec) == 3 and inteiro not in ("0", "-0") and not inteiro.startswith("-0"):
            s = inteiro + dec
    try:
        return float(s)
    except ValueError:
        return None


_MENOR = r"(?:<=?|≤|menor\s+(?:ou\s+igual\s+)?(?:que|a|do\s+que)|inferior\s+a|ate|abaixo\s+de)"
_MAIOR = r"(?:>=?|≥|maior\s+(?:ou\s+igual\s+)?(?:que|a|do\s+que)|superior\s+a|acima\s+de)"


def faixa(referencia: str) -> tuple[float | None, float | None]:
    """Extrai (mínimo, máximo) de textos como '70 a 99', '3,5 - 5,1', '< 200', 'Superior a 40'.

    Referências com várias faixas (por idade, sexo, fase do ciclo, 'desejável/limítrofe')
    devolvem (None, None): nesses casos vale a faixa que o leitor (Claude) escolheu
    para o paciente, ou a classificação fica 'sem_referencia'.
    """
    if not referencia:
        return None, None
    t = sem_acento(referencia).lower().replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", " ", t).strip()
    nums = re.findall(_NUM, t)
    m = re.search(rf"({_NUM})\s*(?:a|-|ate|e)\s*({_NUM})", t)
    if m and len(nums) == 2:
        a, b = numero(m.group(1)), numero(m.group(2))
        if a is not None and b is not None and a <= b:
            return a, b
    if len(nums) == 1:
        if re.search(_MENOR, t):
            return None, numero(nums[0])
        if re.search(_MAIOR, t):
            return numero(nums[0]), None
    return None, None


_NEGATIVOS = {"negativo", "nao reagente", "ausente", "ausentes", "nao detectado", "nao detectavel",
              "indetectavel", "normal", "nao reativo", "inferior ao limite de deteccao"}
_POSITIVOS = {"positivo", "reagente", "presente", "presentes", "detectado", "detectavel", "reativo"}


def classificar(r: Resultado) -> Resultado:
    """Preenche valor_numerico e situacao a partir do valor e da referência."""
    r.valor_numerico = numero(r.valor) if re.search(r"\d", r.valor or "") else None
    if r.referencia:
        mn, mx = faixa(r.referencia)
        if mn is not None or mx is not None:
            r.ref_min, r.ref_max = mn, mx
    v = r.valor_numerico
    if v is not None and (r.ref_min is not None or r.ref_max is not None):
        texto_valor = sem_acento(r.valor).strip()
        if r.ref_min is not None and v < r.ref_min:
            r.situacao = "baixo"
        elif r.ref_max is not None and v > r.ref_max:
            r.situacao = "alto"
        elif r.ref_max is not None and v == r.ref_max and texto_valor.startswith(">"):
            r.situacao = "alto"
        else:
            r.situacao = "normal"
        return r
    val, ref = normalizar(r.valor), normalizar(r.referencia)
    if val and ref and (val == ref or val in ref.split(" ou ")):
        r.situacao = "normal"
    elif val in _POSITIVOS and (ref in _NEGATIVOS or not ref):
        r.situacao = "alterado"
    elif val in _NEGATIVOS and (ref in _NEGATIVOS or not ref):
        r.situacao = "normal"
    else:
        r.situacao = "sem_referencia"
    return r


_UNIDADE_EQUIV = {
    "meq l": "mmol l",
    "mm3": "ul",
    "mcl": "ul",
    "mil mm3": "mil ul",
    "mil mcl": "mil ul",
    "milhoes mm3": "milhoes ul",
    "milhoes mcl": "milhoes ul",
    "mui ml": "uui ml",
    "uui ml": "uui ml",
    "miu l": "uui ml",
}


def unidade(u: str) -> str:
    """Normaliza a unidade para comparação ('mEq/L' == 'mmol/L', '/mm³' == '/µL')."""
    t = (u or "").replace("³", "3").replace("µ", "u").replace("μ", "u")
    t = re.sub(r"x?\s*10\s*\^?\s*3(?!\d)", " mil ", t, flags=re.IGNORECASE)
    t = re.sub(r"x?\s*10\s*\^?\s*6(?!\d)", " milhoes ", t, flags=re.IGNORECASE)
    t = normalizar(t)
    return _UNIDADE_EQUIV.get(t, t)
