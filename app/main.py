"""API web do SeuLaudoai — o paciente importa o laudo e recebe uma explicação em linguagem simples."""
from __future__ import annotations

import base64
import mimetypes
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, ia
from .analitos import Catalogo
from .extratores import ErroExtracao, criar_extratores
from .interpretacao import interpretar
from .models import Laudo
from .valores import classificar

TAMANHO_MAXIMO = 20 * 1024 * 1024

app = FastAPI(title="SeuLaudoai", version="0.1.0")
catalogo = Catalogo.carregar()
extratores = criar_extratores()
db.init()


@app.middleware("http")
async def exigir_senha(request: Request, call_next):
    """Protege o site com usuário/senha quando SEULAUDO_SENHA está definida."""
    if not config.SENHA or request.url.path == "/saude":
        return await call_next(request)
    cab = request.headers.get("authorization", "")
    if cab.startswith("Basic "):
        try:
            usuario, _, senha = base64.b64decode(cab[6:]).decode().partition(":")
        except Exception:  # noqa: BLE001
            usuario = senha = ""
        if secrets.compare_digest(usuario, config.USUARIO) and secrets.compare_digest(senha, config.SENHA):
            return await call_next(request)
    return Response("Acesso restrito", status_code=401, headers={"WWW-Authenticate": 'Basic realm="SeuLaudoai"'})


@app.get("/saude")
def saude():
    return {"ok": True}


# ------------------------------------------------------------------ apoio
def processar(laudo: Laudo, perfil: dict | None = None) -> Laudo:
    """Classifica cada valor pela referência do laudo, padroniza o analito e checa valores críticos."""
    if perfil:
        laudo.paciente.sexo = laudo.paciente.sexo or perfil.get("sexo") or ""
        laudo.paciente.data_nascimento = laudo.paciente.data_nascimento or perfil.get("data_nascimento") or ""
    for r in laudo.resultados:
        classificar(r)
        catalogo.padronizar(r)
    return laudo


def _perfil(perfil_id: int) -> dict:
    p = db.obter_perfil(perfil_id)
    if not p:
        raise HTTPException(404, "Perfil não encontrado")
    return p


def _laudo(laudo_id: int) -> dict:
    reg = db.obter_laudo(laudo_id)
    if not reg:
        raise HTTPException(404, "Laudo não encontrado")
    return reg


def _detectar_mime(arquivo: UploadFile) -> str:
    mime = arquivo.content_type or ""
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(arquivo.filename or "")[0] or "application/octet-stream"
    return mime


def _historico_anterior(perfil_id: int, laudo_id: int, data_coleta: str) -> dict[str, list[dict]]:
    """Valores anteriores (de outros laudos, coletados antes deste) por código de analito."""
    data = db.data_iso(data_coleta)
    out: dict[str, list[dict]] = {}
    for h in db.historico(perfil_id, antes_do_laudo=laudo_id):
        if data and h["data_coleta"] and h["data_coleta"] >= data:
            continue
        d = h["data_coleta"]
        out.setdefault(h["codigo"], []).append({
            "data": f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else "data não informada",
            "valor": h["valor"], "unidade": h["unidade"], "situacao": h["situacao"],
        })
    return out


# ------------------------------------------------------------------ perfis
class NovoPerfil(BaseModel):
    nome: str
    data_nascimento: str = ""
    sexo: str = ""
    consentimento: bool = False


@app.get("/api/status")
def status():
    ok, motivo = ia.disponivel()
    return {
        "claude": ok, "motivo": motivo,
        "extratores": [{"nome": e.nome, "descricao": e.descricao, "disponivel": e.disponivel()[0]}
                       for e in extratores.values()],
    }


@app.get("/api/perfis")
def listar_perfis():
    return db.listar_perfis()


@app.post("/api/perfis")
def criar_perfil(p: NovoPerfil):
    if not p.nome.strip():
        raise HTTPException(422, "Informe o nome")
    if not p.consentimento:
        raise HTTPException(422, "É preciso aceitar o termo de uso dos dados de saúde")
    pid = db.criar_perfil(p.nome.strip(), p.data_nascimento.strip(), p.sexo.strip().upper()[:1], True)
    return db.obter_perfil(pid)


@app.delete("/api/perfis/{perfil_id}")
def excluir_perfil(perfil_id: int):
    """Exclui o perfil e TODOS os seus laudos, arquivos e resultados (direito de exclusão, LGPD)."""
    _perfil(perfil_id)
    for caminho in db.excluir_perfil(perfil_id):
        db.remover_arquivo(caminho)
    return {"ok": True}


# ------------------------------------------------------------------ laudos
@app.post("/api/laudos")
def novo_laudo(
    perfil_id: int = Form(...),
    extrator: str = Form("claude"),
    arquivo: UploadFile | None = File(None),
    texto: str = Form(""),
):
    perfil = _perfil(perfil_id)
    if extrator not in extratores:
        raise HTTPException(400, f"Extrator desconhecido: {extrator}")
    if arquivo is not None and arquivo.filename:
        conteudo = arquivo.file.read()
        mime = _detectar_mime(arquivo)
        nome = arquivo.filename
    elif texto.strip():
        conteudo, mime, nome = texto.encode("utf-8"), "text/plain", "texto-colado.txt"
    else:
        raise HTTPException(400, "Envie um arquivo ou cole o texto do laudo")
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(413, "Arquivo maior que 20 MB")

    destino = config.UPLOAD_DIR / f"{uuid.uuid4().hex}{Path(nome).suffix.lower()[:6]}"
    destino.write_bytes(conteudo)
    try:
        laudo = processar(extratores[extrator].extrair(conteudo, mime, nome), perfil)
    except ErroExtracao as e:
        lid = db.criar_laudo(perfil_id, nome, str(destino), mime, extrator, "erro", erro=str(e))
        raise HTTPException(422, {"mensagem": str(e), "laudo_id": lid}) from e
    lid = db.criar_laudo(perfil_id, nome, str(destino), mime, extrator, "lido", dados=laudo.model_dump())
    return db.obter_laudo(lid)


@app.get("/api/perfis/{perfil_id}/laudos")
def listar_laudos(perfil_id: int):
    _perfil(perfil_id)
    return db.listar_laudos(perfil_id)


@app.get("/api/laudos/{laudo_id}")
def obter_laudo(laudo_id: int):
    return _laudo(laudo_id)


@app.get("/api/laudos/{laudo_id}/arquivo")
def arquivo_laudo(laudo_id: int):
    reg = _laudo(laudo_id)
    caminho = reg.get("arquivo_path")
    if not caminho or not Path(caminho).exists():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(caminho, media_type=reg.get("mime") or "application/octet-stream")


@app.put("/api/laudos/{laudo_id}")
def conferir_laudo(laudo_id: int, laudo: Laudo):
    """Salva a transcrição conferida/corrigida pelo paciente e atualiza o histórico."""
    reg = _laudo(laudo_id)
    laudo = processar(laudo, db.obter_perfil(reg["perfil_id"]))
    dados = laudo.model_dump()
    db.atualizar_laudo(laudo_id, dados=dados, status="conferido", interpretacao=None, erro=None)
    db.gravar_resultados(laudo_id, reg["perfil_id"], dados)
    return db.obter_laudo(laudo_id)


@app.post("/api/laudos/{laudo_id}/interpretar")
def interpretar_laudo(laudo_id: int, basico: bool = False):
    reg = _laudo(laudo_id)
    if reg["status"] not in ("conferido", "interpretado") or not reg.get("dados"):
        raise HTTPException(409, "Confira e salve a transcrição do laudo antes de interpretar")
    laudo = Laudo.model_validate(reg["dados"])
    hist = _historico_anterior(reg["perfil_id"], laudo_id, laudo.data_coleta)
    try:
        interp = interpretar(laudo, catalogo, hist, usar_claude=not basico)
    except ia.ErroIA as e:
        raise HTTPException(502, str(e)) from e
    db.atualizar_laudo(laudo_id, interpretacao=interp.model_dump(), status="interpretado")
    return db.obter_laudo(laudo_id)


@app.delete("/api/laudos/{laudo_id}")
def excluir_laudo(laudo_id: int):
    _laudo(laudo_id)
    db.remover_arquivo(db.excluir_laudo(laudo_id))
    return {"ok": True}


# --------------------------------------------------------------- histórico
@app.get("/api/perfis/{perfil_id}/historico")
def historico(perfil_id: int):
    """Resultados de todos os laudos conferidos, agrupados por analito, em ordem de data."""
    _perfil(perfil_id)
    grupos: dict[str, dict] = {}
    for h in db.historico(perfil_id):
        a = catalogo.analitos.get(h["codigo"])
        g = grupos.setdefault(h["codigo"], {
            "codigo": h["codigo"],
            "nome": a.nome if a else h["nome"],
            "categoria": a.categoria if a else "",
            "descricao": a.descricao if a else "",
            "pontos": [],
        })
        g["pontos"].append({k: h[k] for k in ("laudo_id", "data_coleta", "valor", "valor_numerico", "unidade",
                                               "ref_min", "ref_max", "situacao")})
    for g in grupos.values():
        ultimo = g["pontos"][-1]
        g["ultimo"] = ultimo
        g["unidade"] = ultimo["unidade"]
    return sorted(grupos.values(), key=lambda g: (g["categoria"], g["nome"]))


# ------------------------------------------------------------ IA para a página
# A página (preview/index.html) roda no navegador. No claude.ai ela usa o Claude da conta de quem
# abre; no seu próprio servidor ela chama estas rotas, que usam a ANTHROPIC_API_KEY do servidor.
# Os laudos continuam guardados só no navegador: o servidor não grava nada destas chamadas.
from .extratores.claude import SCHEMA as SCHEMA_LEITURA  # noqa: E402
from .interpretacao import SCHEMA as SCHEMA_INTERP  # noqa: E402

SYSTEM_PAGINA = "Siga exatamente as instruções e o formato pedidos na mensagem do usuário."
LIMITE_PROMPT = 120_000


def _ia_liberada():
    if not (config.SENHA or config.IA_ABERTA):
        raise HTTPException(403, "Defina SEULAUDO_SENHA no servidor para liberar a IA (evita uso indevido da sua chave).")
    ok, motivo = ia.disponivel()
    if not ok:
        raise HTTPException(503, motivo)


@app.get("/api/ia/status")
def ia_status():
    ok, motivo = ia.disponivel()
    liberada = bool(config.SENHA or config.IA_ABERTA)
    return {"disponivel": ok and liberada, "motivo": motivo if not ok else ("" if liberada else "Defina SEULAUDO_SENHA no servidor."),
            "imagens": {"maxCount": config.MAX_IMAGENS}}


@app.post("/api/ia/json")
def ia_json(tipo: str = Form(...), prompt: str = Form(...), imagens: list[UploadFile] | None = File(None)):
    """Leitura ou interpretação com saída estruturada, com o schema do servidor (não o do navegador)."""
    _ia_liberada()
    schemas = {"leitura": (SCHEMA_LEITURA, config.EFFORT_LEITURA), "interpretacao": (SCHEMA_INTERP, config.EFFORT_INTERPRETACAO)}
    if tipo not in schemas:
        raise HTTPException(400, "Tipo inválido")
    if len(prompt) > LIMITE_PROMPT:
        raise HTTPException(413, "Pedido grande demais")
    imagens = [i for i in (imagens or []) if i.filename][: config.MAX_IMAGENS]
    try:
        blocos = []
        for img in imagens:
            dados = img.file.read()
            if len(dados) > TAMANHO_MAXIMO:
                raise HTTPException(413, "Imagem maior que 20 MB")
            blocos.append(ia.bloco_documento(dados, _detectar_mime(img)))
        schema, effort = schemas[tipo]
        return ia.chamar(SYSTEM_PAGINA, blocos + [{"type": "text", "text": prompt}], schema, effort)
    except ia.ErroIA as e:
        raise HTTPException(502, str(e)) from e


class Conversa(BaseModel):
    mensagens: list[dict]


@app.post("/api/ia/texto")
def ia_texto(c: Conversa):
    """Perguntas do paciente sobre o laudo (texto livre)."""
    _ia_liberada()
    msgs = [{"role": m.get("role"), "content": str(m.get("content", ""))} for m in c.mensagens[-21:]]
    if not msgs or msgs[-1]["role"] != "user" or any(m["role"] not in ("user", "assistant") for m in msgs):
        raise HTTPException(400, "Conversa inválida")
    if sum(len(m["content"]) for m in msgs) > LIMITE_PROMPT:
        raise HTTPException(413, "Conversa grande demais")
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    try:
        return {"text": ia.conversar(SYSTEM_PAGINA, msgs, config.EFFORT_PERGUNTAS), "truncated": False}
    except ia.ErroIA as e:
        raise HTTPException(502, str(e)) from e


# ------------------------------------------------------------ páginas
@app.get("/", include_in_schema=False)
def pagina():
    """A página nova (a mesma da prévia), gerada por preview/build.py."""
    return FileResponse(config.BASE_DIR / "preview" / "index.html", media_type="text/html")


# Versão anterior da interface (usa as rotas /api/perfis e /api/laudos, que guardam no servidor)
app.mount("/classico", StaticFiles(directory=config.BASE_DIR / "static", html=True), name="classico")
