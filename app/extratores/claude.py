"""Leitura do laudo com o Claude (visão + saída estruturada): PDF, foto ou texto."""
from __future__ import annotations

from .. import config, ia
from ..models import Laudo
from .base import ErroExtracao, Extrator

_S = {"type": "string"}
_N = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SCHEMA = _obj(
    {
        "tipo": {"type": "string", "enum": ["laboratorial", "imagem", "outro"]},
        "paciente": _obj({k: _S for k in ("nome", "data_nascimento", "idade", "sexo")}),
        "laboratorio": _S,
        "data_coleta": _S,
        "medico_solicitante": _S,
        "resultados": {
            "type": "array",
            "items": _obj(
                {
                    "exame": _S, "analito": _S, "valor": _S, "unidade": _S, "referencia": _S,
                    "ref_min": _N, "ref_max": _N, "material": _S, "metodo": _S, "observacao": _S,
                }
            ),
        },
        "titulo_exame": _S,
        "achados": _S,
        "conclusao": _S,
        "legibilidade": {"type": "string", "enum": ["boa", "media", "ruim"]},
        "campos_incertos": {"type": "array", "items": _S},
        "alertas_leitura": {"type": "array", "items": _S},
    }
)

SYSTEM = """Você transcreve laudos de exames (resultados) emitidos por laboratórios e clínicas no
Brasil para um formulário estruturado. O paciente vai conferir a transcrição antes de qualquer
interpretação, então a fidelidade ao documento é o que importa.

Regras:
- Transcreva apenas o que está no documento. Nunca invente nem corrija valores. Campo ausente = "".
- Datas no formato DD/MM/AAAA. Sexo: "M", "F" ou "".
- "tipo": "laboratorial" para exames com valores (sangue, urina, fezes, hormônios...); "imagem" para
  ultrassom, raio-X, tomografia, ressonância, mamografia, densitometria, ecocardiograma etc.;
  "outro" para os demais laudos descritivos (anatomopatológico, eletrocardiograma...).
- "resultados": um item por valor medido. Em painéis (hemograma, lipidograma, urina tipo I), cada
  parâmetro é um item, com "exame" = nome do painel e "analito" = nome do parâmetro. No leucograma,
  use os valores absolutos (/mm³ ou /µL) e coloque o percentual em "observacao".
- "valor": exatamente como impresso, mantendo vírgula decimal e sinais (ex.: "13,5", "< 0,5",
  "Negativo", "250.000"). "unidade" como impressa.
- "referencia": o texto completo dos valores de referência daquele item, como impresso.
- "ref_min" / "ref_max": os limites numéricos da faixa que se aplica A ESTE paciente (considere
  sexo, idade e fase quando o laudo trouxer várias faixas). Use null para o limite que não existir
  (ex.: "< 200" -> ref_min null, ref_max 200) e null em ambos quando não houver faixa numérica ou
  quando não der para saber qual faixa se aplica. Para lipídios com metas por risco, use a faixa
  "desejável"/"ótimo" para adultos sem outra indicação.
- Laudos descritivos: preencha "titulo_exame", "achados" (texto do laudo, resumido sem perder
  informação) e "conclusao" (impressão diagnóstica/conclusão, como escrita). Deixe "resultados" vazio,
  salvo medidas numéricas com referência (ex.: densitometria T-score).
- "campos_incertos": caminhos dos campos lidos com dúvida (ex.: "resultados[3].valor").
- "alertas_leitura": problemas que o paciente deve conferir: página cortada, foto ilegível em algum
  trecho, mais de um paciente, documento que não é laudo (ex.: pedido médico, receita) etc.
"""

INSTRUCAO = "Transcreva este laudo para o formulário estruturado."


class ExtratorClaude(Extrator):
    nome = "claude"
    descricao = "Claude — PDF, foto ou texto do laudo"

    def disponivel(self) -> tuple[bool, str]:
        return ia.disponivel()

    def extrair(self, conteudo: bytes, mime: str, nome_arquivo: str) -> Laudo:
        try:
            bloco = ia.bloco_documento(conteudo, mime)
            dados = ia.chamar(SYSTEM, [bloco, {"type": "text", "text": INSTRUCAO}], SCHEMA, config.EFFORT_LEITURA)
            return Laudo.model_validate(dados)
        except ia.ErroIA as e:
            raise ErroExtracao(str(e)) from e
        except ValueError as e:
            raise ErroExtracao(f"Resposta fora do formato esperado: {e}") from e
