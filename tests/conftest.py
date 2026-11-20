"""Isola os testes: banco e laudos enviados vão para um diretório temporário."""
import os
import tempfile

os.environ["SEULAUDO_DADOS"] = tempfile.mkdtemp(prefix="seulaudo-testes-")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
