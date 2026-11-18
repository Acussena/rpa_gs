"""Logs de auditoria em JSON Lines + console, com mascaramento de dados pessoais (LGPD)."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

RE_TELEFONE = re.compile(r"(?<!\d)\(?\d{2}\)?\s?9?\d{4}-\d{4}(?!\d)")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def mascarar_telefone(tel: str) -> str:
    """(11) 92528-4872 -> (11) 9****-**72"""
    digitos = re.sub(r"\D", "", tel or "")
    if len(digitos) < 4:
        return "***"
    return f"({digitos[:2]}) {digitos[2]}****-**{digitos[-2:]}"


def mascarar_email(email: str) -> str:
    """ana1@exemplo.com -> a***@exemplo.com"""
    if not email or "@" not in email:
        return "***"
    usuario, dominio = email.split("@", 1)
    return f"{usuario[:1]}***@{dominio}"


def mascarar_nome(nome: str) -> str:
    """Ana Souza -> A. S."""
    return " ".join(p[0].upper() + "." for p in (nome or "").split() if p) or "***"


def higienizar(texto: str) -> str:
    """Rede de segurança: remove qualquer telefone/e-mail que escape para o log."""
    texto = RE_EMAIL.sub("[email-removido]", texto)
    return RE_TELEFONE.sub("[telefone-removido]", texto)


class FormatoJson(logging.Formatter):
    def __init__(self, execucao_id: str):
        super().__init__()
        self.execucao_id = execucao_id

    def format(self, record: logging.LogRecord) -> str:
        reg = {
            "data_hora": datetime.fromtimestamp(record.created).isoformat(timespec="seconds"),
            "nivel": record.levelname,
            "execucao_id": self.execucao_id,
            "etapa": getattr(record, "etapa", "geral"),
            "mensagem": higienizar(record.getMessage()),
        }
        extra = getattr(record, "dados", None)
        if extra:
            reg["dados"] = json.loads(higienizar(json.dumps(extra, ensure_ascii=False, default=str)))
        if record.exc_info:
            reg["erro"] = higienizar(self.formatException(record.exc_info).splitlines()[-1])
        return json.dumps(reg, ensure_ascii=False)


class FormatoConsole(logging.Formatter):
    CORES = {"INFO": "\033[36m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[41m"}

    def format(self, record: logging.LogRecord) -> str:
        hora = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        etapa = getattr(record, "etapa", "geral")
        if sys.stdout.isatty():
            cor, fim = self.CORES.get(record.levelname, ""), "\033[0m"
        else:                                   # CloudWatch / arquivos: sem códigos de cor
            cor = fim = ""
        return f"{hora} {cor}{record.levelname:<7}{fim} [{etapa}] {higienizar(record.getMessage())}"


class Auditoria:
    """Wrapper fino sobre logging para registrar eventos por etapa."""

    def __init__(self, pasta_logs: Path, execucao_id: str, console: bool = True):
        pasta_logs.mkdir(parents=True, exist_ok=True)
        self.arquivo = pasta_logs / f"bot_{datetime.now():%Y%m%d}.jsonl"
        self.logger = logging.getLogger(f"bocadelobo.{execucao_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.logger.handlers.clear()
        fh = logging.FileHandler(self.arquivo, encoding="utf-8")
        fh.setFormatter(FormatoJson(execucao_id))
        self.logger.addHandler(fh)
        if console:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(FormatoConsole())
            self.logger.addHandler(ch)

    def _log(self, nivel: int, etapa: str, msg: str, dados: dict | None = None, exc: bool = False):
        self.logger.log(nivel, msg, extra={"etapa": etapa, "dados": dados}, exc_info=exc)

    def info(self, etapa, msg, dados=None):
        self._log(logging.INFO, etapa, msg, dados)

    def aviso(self, etapa, msg, dados=None):
        self._log(logging.WARNING, etapa, msg, dados)

    def erro(self, etapa, msg, dados=None, exc=False):
        self._log(logging.ERROR, etapa, msg, dados, exc)

    def fechar(self):
        for h in list(self.logger.handlers):
            h.close()
            self.logger.removeHandler(h)
