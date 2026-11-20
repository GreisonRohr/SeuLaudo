"""Rotas usadas pela página quando ela roda no próprio servidor (fora do claude.ai)."""
import io
import json

import anthropic
import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, ia
from app.extratores.claude import SCHEMA as SCHEMA_LEITURA
from app.main import app

client = TestClient(app)


@pytest.fixture
def claude_simulado(monkeypatch):
    chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content)
        chamadas.append(corpo)
        texto = json.dumps({"ok": True}) if "format" in corpo.get("output_config", {}) else "Resposta educativa."
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": texto}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    monkeypatch.setattr(config, "IA_ABERTA", True)
    ia.definir_cliente(anthropic.Anthropic(api_key="teste", http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    yield chamadas
    ia.definir_cliente(None)


def test_pagina_nova_na_raiz_e_classica_em_classico():
    r = client.get("/")
    assert r.status_code == 200 and "SeuLaudoai" in r.text and "api/ia/status" in r.text
    assert client.get("/classico/").status_code == 200


def test_ia_bloqueada_sem_senha(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    assert client.get("/api/ia/status").json()["disponivel"] is False
    r = client.post("/api/ia/texto", json={"mensagens": [{"role": "user", "content": "oi"}]})
    assert r.status_code == 403 and "SEULAUDO_SENHA" in r.json()["detail"]


def test_leitura_usa_schema_do_servidor_e_imagens(claude_simulado):
    img = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(img, format="PNG")
    r = client.post("/api/ia/json", data={"tipo": "leitura", "prompt": "Transcreva"},
                    files=[("imagens", ("p1.png", img.getvalue(), "image/png"))])
    assert r.status_code == 200 and r.json() == {"ok": True}
    corpo = claude_simulado[0]
    assert corpo["output_config"]["format"]["schema"] == SCHEMA_LEITURA
    assert corpo["messages"][0]["content"][0]["type"] == "image"
    assert corpo["fallbacks"] == "default"
    assert client.post("/api/ia/json", data={"tipo": "outro", "prompt": "x"}).status_code == 400


def test_perguntas_em_texto(claude_simulado):
    r = client.post("/api/ia/texto", json={"mensagens": [
        {"role": "user", "content": "contexto + pergunta 1"}, {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "pergunta 2"}]})
    assert r.status_code == 200 and r.json()["text"] == "Resposta educativa."
    assert [m["role"] for m in claude_simulado[0]["messages"]] == ["user", "assistant", "user"]
    assert client.post("/api/ia/texto", json={"mensagens": [{"role": "system", "content": "x"}]}).status_code == 400
