"""Leitura por regras (sem IA) de laudos em texto e PDFs digitais.

Reconhece linhas no formato comum dos laudos impressos:
    GLICOSE ........: 105 mg/dL      VR: 70 a 99 mg/dL
Serve para testar o fluxo sem chave de API; fotos e laudos complexos pedem o Claude.
"""
from __future__ import annotations

import io
import re

from ..models import Laudo, Resultado
from .base import ErroExtracao, Extrator

_QUALITATIVOS = r"negativo|positivo|n[aã]o reagente|reagente|ausentes?|presentes?|n[aã]o detectado|detectado"
_REF = r"(?:v\.?\s?r\.?|ref\.?|refer[eê]ncia|valor(?:es)? de refer[eê]ncia)"

LINHA = re.compile(
    rf"""^\s*(?P<nome>[A-Za-zÀ-ú][A-Za-zÀ-ú0-9 ()/\-,]*?)\s*(?:\.{{2,}}|:)[\s.:]*
         (?P<valor>[<>≤≥]?\s*\d[\d.,]*|{_QUALITATIVOS})
         \s*(?P<unidade>[^\s\d:][^\s]*)?
         \s*(?:{_REF}\s*:?\s*(?P<ref>.+?))?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

CABECALHO = {
    "paciente.nome": r"^\s*(?:paciente|nome)\s*:\s*(.+?)\s*$",
    "paciente.data_nascimento": r"(?:data de )?nascimento\s*:\s*(\d{2}/\d{2}/\d{4})",
    "paciente.idade": r"idade\s*:\s*([^\n|]+?)\s*(?:\||$)",
    "paciente.sexo": r"sexo\s*:\s*([MF])",
    "data_coleta": r"(?:data (?:da )?coleta|coletado em|coleta)\s*:\s*(\d{2}/\d{2}/\d{4})",
    "laboratorio": r"^\s*(?:laborat[oó]rio)\s*:\s*(.+?)\s*$",
    "medico_solicitante": r"^\s*(?:m[eé]dico(?: solicitante)?|solicitante|dr\(a\)\.?)\s*:\s*(.+?)\s*$",
}

_IGNORAR = re.compile(r"^(?:paciente|nome|nascimento|data|idade|sexo|coleta|laborat|m[eé]dico|solicitante|"
                      r"material|m[eé]todo|liberado|assinado|p[aá]gina)", re.IGNORECASE)


def _pdf_texto(conteudo: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ErroExtracao("Instale pypdf para ler PDFs sem IA.") from e
    try:
        texto = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(conteudo)).pages)
    except Exception as e:  # noqa: BLE001
        raise ErroExtracao("Não foi possível ler o PDF.") from e
    if not texto.strip():
        raise ErroExtracao("O PDF não tem texto (é uma imagem digitalizada). Use o extrator Claude.")
    return texto


class ExtratorTexto(Extrator):
    nome = "texto"
    descricao = "Regras (sem IA) — texto e PDFs digitais"

    def extrair(self, conteudo: bytes, mime: str, nome_arquivo: str) -> Laudo:
        if mime == "application/pdf":
            texto = _pdf_texto(conteudo)
        elif mime.startswith("text/"):
            texto = conteudo.decode("utf-8", "replace")
        else:
            raise ErroExtracao("O extrator por regras lê apenas texto e PDF digital. Para fotos, use o Claude.")
        return ler_texto(texto)


def ler_texto(texto: str) -> Laudo:
    laudo = Laudo()
    for campo, padrao in CABECALHO.items():
        m = re.search(padrao, texto, re.IGNORECASE | re.MULTILINE)
        if m:
            alvo, _, attr = campo.rpartition(".")
            setattr(laudo.paciente if alvo else laudo, attr, m.group(1).strip())
    laudo.paciente.sexo = laudo.paciente.sexo.upper()

    exame_atual = ""
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        m = LINHA.match(linha)
        if m and not _IGNORAR.match(linha.strip()):
            unidade = (m.group("unidade") or "").strip()
            if re.fullmatch(_REF, unidade, re.IGNORECASE):
                unidade = ""
            laudo.resultados.append(Resultado(
                exame=exame_atual or m.group("nome").strip(),
                analito=m.group("nome").strip(),
                valor=re.sub(r"\s+", " ", m.group("valor")).strip(),
                unidade=unidade,
                referencia=(m.group("ref") or "").strip(),
            ))
        elif linha.strip().isupper() and len(linha.strip()) > 3 and ":" not in linha:
            exame_atual = linha.strip().title()  # título de seção, ex.: "HEMOGRAMA COMPLETO"
    if not laudo.resultados:
        laudo.alertas_leitura.append("Nenhum resultado reconhecido pelas regras. Tente o extrator Claude.")
    laudo.legibilidade = "boa"
    return laudo
