import pytest

from app.analitos import Catalogo
from app.models import Resultado
from app.valores import classificar, faixa, numero, unidade


@pytest.mark.parametrize("texto,esperado", [
    ("12,5", 12.5), ("1.234,5", 1234.5), ("250.000", 250000), ("4.5", 4.5), ("0,85", 0.85),
    ("< 0,5", 0.5), ("6.800", 6800), ("13.50", 13.5), ("Negativo", None),
])
def test_numero(texto, esperado):
    assert numero(texto) == esperado


@pytest.mark.parametrize("ref,esperado", [
    ("70 a 99 mg/dL", (70, 99)), ("3,5 - 5,1", (3.5, 5.1)), ("Inferior a 190 mg/dL", (None, 190)),
    ("< 200", (None, 200)), ("Superior a 40 mg/dL", (40, None)), ("Até 5,0", (None, 5.0)),
    ("150.000 a 450.000 /mm³", (150000, 450000)), ("Negativo", (None, None)),
    ("Ótimo: < 100; Desejável: 100 a 129; Limítrofe: 130 a 159", (None, None)),
])
def test_faixa(ref, esperado):
    assert faixa(ref) == esperado


def _r(valor, referencia="", **kw):
    return classificar(Resultado(analito="X", valor=valor, referencia=referencia, **kw))


def test_classificacao():
    assert _r("112", "70 a 99").situacao == "alto"
    assert _r("65", "70 a 99").situacao == "baixo"
    assert _r("99", "70 a 99").situacao == "normal"
    assert _r("52", "Superior a 40").situacao == "normal"
    assert _r("Positivo", "Negativo").situacao == "alterado"
    assert _r("Não reagente", "Não reagente").situacao == "normal"
    assert _r("7,2", "").situacao == "sem_referencia"
    # faixa com várias opções: vale a faixa que o leitor escolheu para o paciente
    r = _r("135", "Ótimo < 100; Desejável 100 a 129", ref_max=129)
    assert r.situacao == "alto" and r.ref_max == 129


def test_unidade():
    assert unidade("mEq/L") == unidade("mmol/L")
    assert unidade("/mm³") == unidade("/µL")
    assert unidade("x10³/µL") == unidade("mil/mm³")


def test_catalogo_padroniza_e_valores_criticos():
    c = Catalogo.carregar()
    assert c.identificar("Glicemia de jejum").codigo == "GLI"
    assert c.identificar("TGO").codigo == "TGO"
    assert c.identificar("Colesterol HDL").codigo == "HDL"
    assert c.identificar("Colesterol LDL").codigo == "LDL"
    assert c.identificar("Exame inexistente qualquer") is None
    r = c.padronizar(classificar(Resultado(analito="Potássio", valor="6,8", unidade="mEq/L", referencia="3,5 a 5,1")))
    assert r.codigo == "K" and r.critico and r.situacao == "alto"
    r = c.padronizar(classificar(Resultado(analito="Potássio", valor="5,4", unidade="mmol/L", referencia="3,5 a 5,1")))
    assert not r.critico
    # plaquetas em unidades diferentes
    assert c.padronizar(classificar(Resultado(analito="Plaquetas", valor="15.000", unidade="/mm³"))).critico
    assert c.padronizar(classificar(Resultado(analito="Plaquetas", valor="15", unidade="mil/mm³"))).critico
    assert not c.padronizar(classificar(Resultado(analito="Plaquetas", valor="150", unidade="mil/mm³"))).critico
