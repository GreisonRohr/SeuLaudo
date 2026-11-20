"""Modelos de dados do laudo e da interpretação."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Situacao = Literal["normal", "alto", "baixo", "alterado", "sem_referencia", ""]


class Resultado(BaseModel):
    """Um analito (item) do laudo, como impresso pelo laboratório."""

    exame: str = ""  # nome do exame/grupo (ex.: "Hemograma completo")
    analito: str = ""  # nome do item como no laudo (ex.: "Hemoglobina")
    valor: str = ""  # como impresso (ex.: "13,5", "Negativo", "< 0,5")
    unidade: str = ""
    referencia: str = ""  # faixa de referência como impressa
    ref_min: float | None = None  # faixa aplicável ao paciente, quando numérica
    ref_max: float | None = None
    material: str = ""
    metodo: str = ""
    observacao: str = ""
    # Calculados pelo sistema (nunca pela IA)
    valor_numerico: float | None = None
    situacao: Situacao = ""
    codigo: str = ""  # código padronizado do analito (data/analitos.csv), para o histórico
    nome_padrao: str = ""
    critico: bool = False
    mensagem_critica: str = ""


class Paciente(BaseModel):
    nome: str = ""
    data_nascimento: str = ""  # DD/MM/AAAA
    idade: str = ""
    sexo: str = ""  # M, F ou vazio


class Laudo(BaseModel):
    tipo: Literal["laboratorial", "imagem", "outro"] = "laboratorial"
    paciente: Paciente = Field(default_factory=Paciente)
    laboratorio: str = ""
    data_coleta: str = ""  # DD/MM/AAAA
    medico_solicitante: str = ""
    resultados: list[Resultado] = Field(default_factory=list)
    # Laudos descritivos (imagem, anatomopatológico): texto e conclusão
    titulo_exame: str = ""
    achados: str = ""
    conclusao: str = ""
    legibilidade: Literal["boa", "media", "ruim", ""] = ""
    campos_incertos: list[str] = Field(default_factory=list)
    alertas_leitura: list[str] = Field(default_factory=list)


# ------------------------------------------------------------- interpretação
class ItemInterpretado(BaseModel):
    indice: int  # posição do resultado em Laudo.resultados (-1 = laudo descritivo)
    titulo: str = ""
    o_que_e: str = ""  # o que o exame mede, em linguagem simples
    seu_resultado: str = ""  # o que o valor significa em relação à referência
    possiveis_causas: list[str] = Field(default_factory=list)  # quando alterado
    fonte: Literal["claude", "basico"] = "basico"


class ExameSugerido(BaseModel):
    exame: str
    motivo: str


class Interpretacao(BaseModel):
    resumo: str = ""
    destaques: list[str] = Field(default_factory=list)  # pontos principais, frases curtas
    itens: list[ItemInterpretado] = Field(default_factory=list)
    perguntas_medico: list[str] = Field(default_factory=list)
    exames_para_conversar: list[ExameSugerido] = Field(default_factory=list)
    habitos: list[str] = Field(default_factory=list)  # orientações gerais de estilo de vida
    procurar_atendimento: list[str] = Field(default_factory=list)  # alertas de urgência
    acompanhamento: str = ""  # quando costuma ser repetido / como acompanhar
    modo: Literal["claude", "basico"] = "basico"
    aviso: str = (
        "Esta interpretação é educativa e não substitui a avaliação do seu médico. "
        "Não use estas informações para iniciar, mudar ou interromper tratamentos."
    )
