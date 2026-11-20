"""Leitura e interpretação com o Claude, sem rede: o HTTP é interceptado e a resposta é simulada."""
import io
import json

import anthropic
import httpx2 as httpx
from fastapi.testclient import TestClient
from PIL import Image

from app import ia
from app.main import app

LEITURA = {
    "tipo": "laboratorial",
    "paciente": {"nome": "Ana Teste", "data_nascimento": "01/01/1980", "idade": "46 anos", "sexo": "F"},
    "laboratorio": "Lab Simulado", "data_coleta": "05/11/2026", "medico_solicitante": "",
    "resultados": [
        {"exame": "Bioquímica", "analito": "Glicemia de jejum", "valor": "126", "unidade": "mg/dL",
         "referencia": "70 a 99 mg/dL", "ref_min": 70, "ref_max": 99, "material": "Soro", "metodo": "", "observacao": ""},
        {"exame": "Lipidograma", "analito": "LDL", "valor": "160", "unidade": "mg/dL",
         "referencia": "Ótimo: < 100; Desejável: 100 a 129", "ref_min": None, "ref_max": 129,
         "material": "", "metodo": "", "observacao": ""},
    ],
    "titulo_exame": "", "achados": "", "conclusao": "", "legibilidade": "boa",
    "campos_incertos": ["resultados[1].valor"], "alertas_leitura": [],
}

INTERPRETACAO = {
    "resumo": "Dois resultados ficaram acima da referência.",
    "itens": [
        {"indice": 0, "titulo": "Glicose", "o_que_e": "Açúcar no sangue.", "seu_resultado": "Acima.",
         "possiveis_causas": ["Jejum inadequado"]},
        {"indice": 9, "titulo": "Fora da lista", "o_que_e": "", "seu_resultado": "", "possiveis_causas": []},
    ],
    "perguntas_medico": ["Preciso repetir a glicose?"],
    "exames_para_conversar": [{"exame": "Hemoglobina glicada", "motivo": "Mostra a média dos últimos meses."}],
    "habitos": ["Atividade física regular."],
    "procurar_atendimento": [],
    "acompanhamento": "A critério do médico.",
}


def _resposta(dados):
    return httpx.Response(200, json={
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": json.dumps(dados, ensure_ascii=False)}],
        "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 10},
    })


def test_leitura_e_interpretacao_com_claude(monkeypatch):
    chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        chamadas.append((corpo, request.headers.get("anthropic-beta", "")))
        return _resposta(LEITURA if len(chamadas) == 1 else INTERPRETACAO)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    ia.definir_cliente(anthropic.Anthropic(api_key="teste", http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    try:
        client = TestClient(app)
        pid = client.post("/api/perfis", json={"nome": "Ana", "consentimento": True}).json()["id"]
        img = io.BytesIO()
        Image.new("RGB", (3000, 1200), "white").save(img, format="PNG")
        r = client.post("/api/laudos", data={"perfil_id": pid, "extrator": "claude"},
                        files={"arquivo": ("laudo.png", img.getvalue(), "image/png")})
        assert r.status_code == 200, r.text
        reg = r.json()
        res = reg["dados"]["resultados"]
        assert res[0]["codigo"] == "GLI" and res[0]["situacao"] == "alto"
        # referência com várias faixas: vale o limite escolhido pelo leitor
        assert res[1]["codigo"] == "LDL" and res[1]["situacao"] == "alto"

        corpo, beta = chamadas[0]
        assert corpo["model"] == "claude-opus-5-5"
        assert corpo["output_config"]["format"]["type"] == "json_schema"
        assert corpo["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in beta
        bloco = corpo["messages"][0]["content"][0]
        assert bloco["type"] == "image" and bloco["source"]["media_type"] == "image/jpeg"

        client.put(f"/api/laudos/{reg['id']}", json=reg["dados"])
        r = client.post(f"/api/laudos/{reg['id']}/interpretar")
        assert r.status_code == 200, r.text
        interp = r.json()["interpretacao"]
        assert interp["modo"] == "claude"
        assert [i["indice"] for i in interp["itens"]] == [0]  # índice inválido descartado
        assert interp["exames_para_conversar"][0]["exame"] == "Hemoglobina glicada"

        texto_enviado = chamadas[1][0]["messages"][0]["content"][0]["text"]
        assert "Ana Teste" not in texto_enviado  # o nome não vai para a interpretação
        assert '"situacao": "alto"' in texto_enviado
    finally:
        ia.definir_cliente(None)


def test_recusa_do_modelo_vira_erro_amigavel(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "id": "msg_2", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [], "stop_reason": "refusal", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 0},
        })

    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    ia.definir_cliente(anthropic.Anthropic(api_key="teste", http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    try:
        client = TestClient(app)
        pid = client.post("/api/perfis", json={"nome": "Recusa", "consentimento": True}).json()["id"]
        r = client.post("/api/laudos", data={"perfil_id": pid, "extrator": "claude", "texto": "Glicose: 90 mg/dL"})
        assert r.status_code == 422 and "recusou" in r.json()["detail"]["mensagem"]
    finally:
        ia.definir_cliente(None)
