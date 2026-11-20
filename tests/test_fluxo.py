"""Fluxo completo pela API, sem IA: perfil -> envio -> conferência -> interpretação -> histórico."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
EXEMPLO = (Path(__file__).parent.parent / "exemplos" / "laudo_exemplo.txt").read_text(encoding="utf-8")


def _perfil(nome="Maria"):
    r = client.post("/api/perfis", json={"nome": nome, "sexo": "F", "consentimento": True})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _enviar(pid, texto=EXEMPLO):
    r = client.post("/api/laudos", data={"perfil_id": pid, "extrator": "texto", "texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def test_perfil_exige_consentimento():
    r = client.post("/api/perfis", json={"nome": "Sem aceite", "consentimento": False})
    assert r.status_code == 422


def test_fluxo_completo():
    pid = _perfil()
    reg = _enviar(pid)
    assert reg["status"] == "lido"
    dados = reg["dados"]
    assert len(dados["resultados"]) == 15
    glicose = next(r for r in dados["resultados"] if r["codigo"] == "GLI")
    assert glicose["situacao"] == "alto"

    # interpretar antes de conferir não é permitido
    assert client.post(f"/api/laudos/{reg['id']}/interpretar?basico=true").status_code == 409

    # paciente corrige um valor na conferência: a situação é recalculada pelo sistema
    hb = next(r for r in dados["resultados"] if r["codigo"] == "HB")
    hb["valor"] = "12,8"
    r = client.put(f"/api/laudos/{reg['id']}", json=dados)
    assert r.status_code == 200
    hb = next(x for x in r.json()["dados"]["resultados"] if x["codigo"] == "HB")
    assert hb["situacao"] == "normal"

    r = client.post(f"/api/laudos/{reg['id']}/interpretar?basico=true")
    assert r.status_code == 200, r.text
    interp = r.json()["interpretacao"]
    assert interp["modo"] == "basico"
    assert "Glicose" in interp["resumo"] and interp["perguntas_medico"]
    assert interp["procurar_atendimento"] == []

    lista = client.get(f"/api/perfis/{pid}/laudos").json()
    assert lista[0]["qtd_resultados"] == 15 and lista[0]["status"] == "interpretado"


def test_historico_e_valor_critico():
    pid = _perfil("Histórico")
    a = _enviar(pid)
    client.put(f"/api/laudos/{a['id']}", json=a["dados"])

    segundo = EXEMPLO.replace("10/11/2026", "10/02/2027").replace("4,3 mEq/L", "6,9 mEq/L").replace("112 mg/dL", "98 mg/dL")
    b = _enviar(pid, segundo)
    client.put(f"/api/laudos/{b['id']}", json=b["dados"])
    interp = client.post(f"/api/laudos/{b['id']}/interpretar?basico=true").json()["interpretacao"]
    assert any("Potássio" in a for a in interp["procurar_atendimento"])
    item_gli = next(i for i in interp["itens"] if i["titulo"] == "Glicose")
    assert "10/11/2026" in item_gli["seu_resultado"]  # compara com o exame anterior

    hist = {g["codigo"]: g for g in client.get(f"/api/perfis/{pid}/historico").json()}
    assert [p["valor"] for p in hist["GLI"]["pontos"]] == ["112", "98"]
    assert hist["GLI"]["ultimo"]["situacao"] == "normal"


def test_exclusao_do_perfil_apaga_tudo():
    pid = _perfil("Excluir")
    reg = _enviar(pid)
    from app import db
    caminho = Path(db.obter_laudo(reg["id"])["arquivo_path"])
    assert caminho.exists()
    assert client.delete(f"/api/perfis/{pid}").status_code == 200
    assert not caminho.exists()
    assert client.get(f"/api/laudos/{reg['id']}").status_code == 404
    assert client.get(f"/api/perfis/{pid}/historico").status_code == 404


def test_claude_indisponivel_sem_chave():
    s = client.get("/api/status").json()
    assert s["claude"] is False
    pid = _perfil("Sem chave")
    r = client.post("/api/laudos", data={"perfil_id": pid, "extrator": "claude", "texto": "Glicose: 90"})
    assert r.status_code == 422 and "ANTHROPIC_API_KEY" in r.json()["detail"]["mensagem"]
