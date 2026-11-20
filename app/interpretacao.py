"""Interpretação do laudo em linguagem simples.

Divisão de responsabilidades (segurança):
- Regras do sistema: classificação de cada valor (normal/alto/baixo) pela referência do
  próprio laudo e alertas de valores críticos. Isso nunca depende da IA.
- Claude: explicação em linguagem simples, resumo, perguntas para o médico, exames para
  conversar com o médico e orientações gerais — sempre em tom educativo, sem diagnóstico.
- Sem chave de API: interpretação básica com as descrições do catálogo de analitos.
"""
from __future__ import annotations

import json

from . import config, ia
from .analitos import Catalogo
from .models import ExameSugerido, Interpretacao, ItemInterpretado, Laudo

_S = {"type": "string"}
_LS = {"type": "array", "items": _S}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


SCHEMA = _obj(
    {
        "resumo": _S,
        "itens": {
            "type": "array",
            "items": _obj({"indice": {"type": "integer"}, "titulo": _S, "o_que_e": _S,
                           "seu_resultado": _S, "possiveis_causas": _LS}),
        },
        "perguntas_medico": _LS,
        "exames_para_conversar": {"type": "array", "items": _obj({"exame": _S, "motivo": _S})},
        "habitos": _LS,
        "procurar_atendimento": _LS,
        "acompanhamento": _S,
    }
)

SYSTEM = """Você ajuda pacientes brasileiros a entender o laudo dos próprios exames. O texto será lido
pelo paciente, não por um profissional de saúde. Seu papel é educativo: explicar, contextualizar e
preparar o paciente para conversar com o médico. Você não diagnostica, não prescreve e não substitui
a consulta.

Escreva em português do Brasil, em linguagem simples (como para alguém sem formação em saúde),
frases curtas, tom calmo e respeitoso. Evite jargão; quando um termo técnico for necessário,
explique-o. Não use alarmismo nem falsa tranquilidade.

Você recebe o laudo já transcrito e conferido pelo paciente, em JSON. Para cada resultado, o campo
"situacao" foi calculado pelo sistema comparando o valor com a referência do próprio laudo:
"normal", "alto", "baixo", "alterado" (qualitativo fora do esperado) ou "sem_referencia".
Respeite essa classificação: não a contradiga. Quando houver "historico", são valores anteriores do
mesmo exame deste paciente (de outros laudos); comente a evolução quando for relevante.

Regras de conteúdo:
- Nunca afirme que o paciente tem uma doença. Use "pode estar relacionado a", "costuma ser
  investigado", "o médico pode avaliar se...".
- Considere os resultados em conjunto (ex.: hemoglobina baixa + VCM baixo + ferritina baixa sugerem
  investigar falta de ferro; glicose e hemoglobina glicada juntas).
- Nunca indique medicamentos, doses, suplementos específicos ou mudanças de tratamento.
- "exames_para_conversar": exames complementares que um médico costuma considerar diante destes
  resultados, com o motivo em uma frase. Apresente como algo para conversar com o médico, nunca
  como ordem. Lista vazia se nada fizer sentido. No máximo 5.
- "perguntas_medico": 3 a 6 perguntas objetivas que o paciente pode levar à consulta.
- "habitos": orientações gerais e seguras de estilo de vida ligadas aos achados (alimentação,
  atividade física, sono, álcool, hidratação). Lista vazia se não houver nada pertinente.
- "procurar_atendimento": sinais ou situações deste laudo que pedem procurar atendimento médico
  rapidamente ou pronto-socorro (ex.: resultados com "critico": true, troponina positiva, achado de
  imagem descrito como urgente). Diga o que fazer de forma clara. Lista vazia se não houver.
- "acompanhamento": em 1 a 3 frases, como esses exames costumam ser acompanhados (ex.: repetir após
  tratamento, a critério do médico). Não defina prazos rígidos.
- "itens": um item para cada resultado alterado ("alto", "baixo", "alterado") e para os normais que
  ajudem a entender o conjunto; "indice" é a posição do resultado na lista "resultados" (começando
  em 0). Em laudos descritivos (imagem e outros), faça itens com indice -1 explicando os achados e
  a conclusão, termo a termo. "o_que_e": o que o exame mede (1 a 2 frases). "seu_resultado": o que
  o valor significa em relação à referência (1 a 3 frases). "possiveis_causas": causas comuns,
  incluindo as que não são doença (jejum, exercício, hidratação, medicamentos, ciclo menstrual);
  vazia para resultados normais.
- "resumo": 3 a 6 frases com a visão geral do laudo: o que está dentro do esperado, o que chama
  atenção e o próximo passo (conversar com o médico).
- Se o laudo não parecer um laudo de exame, diga isso no resumo e deixe as listas vazias.
"""

PERGUNTAS_BASICAS = [
    "Algum destes resultados precisa de tratamento ou de novos exames?",
    "Quando devo repetir os exames que vieram fora da referência?",
    "Algum medicamento que uso pode ter interferido nos resultados?",
    "Há algo que eu possa mudar na alimentação ou nos hábitos para melhorar estes valores?",
]

SITUACAO_TEXTO = {
    "normal": "Seu resultado está dentro da faixa de referência informada pelo laboratório.",
    "alto": "Seu resultado está acima da faixa de referência informada pelo laboratório.",
    "baixo": "Seu resultado está abaixo da faixa de referência informada pelo laboratório.",
    "alterado": "Seu resultado está diferente do esperado pela referência do laboratório.",
    "sem_referencia": "O laudo não traz uma faixa de referência que permita comparar este valor automaticamente.",
}


def _entrada(laudo: Laudo, historico: dict[str, list[dict]]) -> dict:
    dados = laudo.model_dump(exclude={"campos_incertos", "alertas_leitura", "legibilidade"})
    dados["paciente"].pop("nome", None)  # o nome não é necessário para interpretar
    for r in dados["resultados"]:
        if r["codigo"] in historico:
            r["historico"] = historico[r["codigo"]]
        for k in ("valor_numerico", "nome_padrao", "mensagem_critica"):
            r.pop(k, None)
    return dados


def _alertas_criticos(laudo: Laudo) -> list[str]:
    return [
        f"{r.analito or r.nome_padrao}: {r.valor} {r.unidade}. {r.mensagem_critica} "
        "Procure atendimento médico o quanto antes e leve este laudo."
        for r in laudo.resultados if r.critico
    ]


def interpretar(laudo: Laudo, catalogo: Catalogo, historico: dict[str, list[dict]] | None = None,
                usar_claude: bool = True) -> Interpretacao:
    historico = historico or {}
    if usar_claude and ia.disponivel()[0]:
        entrada = json.dumps(_entrada(laudo, historico), ensure_ascii=False, indent=1)
        dados = ia.chamar(
            SYSTEM,
            [{"type": "text", "text": "Laudo conferido pelo paciente:\n\n" + entrada},
             {"type": "text", "text": "Explique este laudo para o paciente seguindo as regras."}],
            SCHEMA,
            config.EFFORT_INTERPRETACAO,
        )
        interp = Interpretacao.model_validate({**dados, "modo": "claude"})
        n = len(laudo.resultados)
        interp.itens = [i for i in interp.itens if -1 <= i.indice < n]
        for i in interp.itens:
            i.fonte = "claude"
    else:
        interp = interpretacao_basica(laudo, catalogo, historico)
    # alertas de valores críticos vêm das regras do sistema, sempre
    criticos = _alertas_criticos(laudo)
    interp.procurar_atendimento = criticos + [a for a in interp.procurar_atendimento if a not in criticos]
    return interp


def interpretacao_basica(laudo: Laudo, catalogo: Catalogo, historico: dict[str, list[dict]]) -> Interpretacao:
    itens = []
    fora = []
    for i, r in enumerate(laudo.resultados):
        if r.situacao in ("alto", "baixo", "alterado"):
            fora.append(r.analito or r.nome_padrao)
        texto = SITUACAO_TEXTO.get(r.situacao, "")
        anteriores = historico.get(r.codigo) or []
        if anteriores:
            ultimo = anteriores[-1]
            texto += f" No exame anterior ({ultimo['data']}) o valor foi {ultimo['valor']} {ultimo['unidade']}."
        itens.append(ItemInterpretado(
            indice=i,
            titulo=r.nome_padrao or r.analito,
            o_que_e=catalogo.descricao(r.codigo) or "Descrição ainda não disponível para este exame.",
            seu_resultado=texto,
        ))
    if laudo.tipo != "laboratorial" and laudo.conclusao:
        itens.append(ItemInterpretado(indice=-1, titulo=laudo.titulo_exame or "Conclusão do laudo",
                                      seu_resultado=laudo.conclusao))
    total = len(laudo.resultados)
    if fora:
        resumo = (f"De {total} resultados, {len(fora)} ficaram fora da faixa de referência do laboratório: "
                  f"{', '.join(fora)}. Isso não significa necessariamente uma doença, mas vale conversar "
                  "com seu médico sobre eles.")
    elif total:
        resumo = f"Os {total} resultados deste laudo estão dentro das faixas de referência do laboratório."
    else:
        resumo = "Não há resultados numéricos neste laudo para comparar automaticamente."
    return Interpretacao(
        resumo=resumo + " (Interpretação básica, sem IA: configure a chave da API para uma explicação completa.)",
        itens=itens,
        perguntas_medico=PERGUNTAS_BASICAS if fora else PERGUNTAS_BASICAS[2:3],
        exames_para_conversar=[] if not fora else [ExameSugerido(
            exame="Avaliação com o médico que pediu os exames",
            motivo="Ele pode dizer se os valores alterados pedem novos exames ou acompanhamento.")],
        acompanhamento="A frequência de repetição dos exames depende do seu histórico e deve ser definida pelo seu médico.",
        modo="basico",
    )
