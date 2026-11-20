from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Laudo


class ErroExtracao(Exception):
    """Falha ao ler o laudo (mensagem pensada para o usuário)."""


class Extrator(ABC):
    nome: str = ""
    descricao: str = ""

    def disponivel(self) -> tuple[bool, str]:
        return True, ""

    @abstractmethod
    def extrair(self, conteudo: bytes, mime: str, nome_arquivo: str) -> Laudo: ...
