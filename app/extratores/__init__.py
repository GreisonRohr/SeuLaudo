from .base import ErroExtracao, Extrator
from .claude import ExtratorClaude
from .texto import ExtratorTexto


def criar_extratores() -> dict[str, Extrator]:
    return {e.nome: e for e in (ExtratorClaude(), ExtratorTexto())}


__all__ = ["ErroExtracao", "Extrator", "criar_extratores"]
