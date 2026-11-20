"""Chamada ao Claude com saída estruturada (JSON Schema), usada na leitura e na interpretação."""
from __future__ import annotations

import base64
import io
import json
import os

import anthropic

from . import config

MIME_IMAGEM = {"image/jpeg", "image/png", "image/webp", "image/gif"}
LADO_MAXIMO_PX = 2000

_client: anthropic.Anthropic | None = None


class ErroIA(Exception):
    """Falha na chamada ao Claude (mensagem pensada para o usuário)."""


def disponivel() -> tuple[bool, str]:
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return True, ""
    return False, "Defina ANTHROPIC_API_KEY no ambiente para usar o Claude."


def cliente() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def definir_cliente(c: anthropic.Anthropic | None):
    """Permite injetar um cliente simulado nos testes."""
    global _client
    _client = c


def bloco_documento(conteudo: bytes, mime: str) -> dict:
    if mime == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                               "data": base64.standard_b64encode(conteudo).decode()}}
    if mime.startswith("image/"):
        dados, mime_final = _preparar_imagem(conteudo, mime)
        return {"type": "image", "source": {"type": "base64", "media_type": mime_final,
                                            "data": base64.standard_b64encode(dados).decode()}}
    if mime.startswith("text/"):
        return {"type": "text", "text": "Conteúdo do laudo:\n\n" + conteudo.decode("utf-8", "replace")}
    raise ErroIA(f"Tipo de arquivo não suportado: {mime}. Use PDF, foto (JPG, PNG, WEBP) ou texto.")


def chamar(system: str, conteudo: list[dict], schema: dict, effort: str, max_tokens: int = 16000) -> dict:
    ok, motivo = disponivel()
    if not ok:
        raise ErroIA(motivo)
    try:
        resposta = cliente().beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": conteudo}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # se o modelo recusar por política, a API repete a chamada num modelo de fallback
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise ErroIA("Chave da API inválida (ANTHROPIC_API_KEY).") from e
    except anthropic.RateLimitError as e:
        raise ErroIA("Limite de requisições da API atingido; tente novamente em instantes.") from e
    except anthropic.BadRequestError as e:
        raise ErroIA(f"A API rejeitou o pedido: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise ErroIA(f"Erro da API ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ErroIA("Sem conexão com a API da Anthropic.") from e

    if resposta.stop_reason == "refusal":
        raise ErroIA("O modelo recusou processar este documento.")
    if resposta.stop_reason == "max_tokens":
        raise ErroIA("Resposta truncada (documento grande demais).")
    texto = next((b.text for b in resposta.content if b.type == "text"), None)
    if not texto:
        raise ErroIA("Resposta sem conteúdo.")
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        raise ErroIA(f"Resposta fora do formato esperado: {e}") from e


def _preparar_imagem(conteudo: bytes, mime: str) -> tuple[bytes, str]:
    """Corrige rotação EXIF (fotos de celular) e reduz imagens muito grandes."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if mime not in MIME_IMAGEM:
            raise ErroIA(f"Formato de imagem não suportado: {mime}")
        return conteudo, mime
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(conteudo)))
    except Exception as e:  # noqa: BLE001
        raise ErroIA(f"Não foi possível abrir a imagem ({mime}). Use JPG, PNG ou WEBP.") from e
    if max(img.size) > LADO_MAXIMO_PX:
        img.thumbnail((LADO_MAXIMO_PX, LADO_MAXIMO_PX))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"
