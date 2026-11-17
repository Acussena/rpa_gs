"""Carregamento da configuração e dos caminhos usados pelo bot."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ConfiguracaoInvalida(Exception):
    """Arquivo de configuração ausente ou com campos obrigatórios faltando."""


CAMPOS_OBRIGATORIOS = [
    "latitude", "longitude", "api_previsao", "limites_chuva", "score",
    "faixas_prioridade", "prioridades_por_nivel", "equipes_limpeza",
]


@dataclass
class Caminhos:
    base: Path

    @property
    def config(self) -> Path:
        return self.base / "config" / "config.json"

    @property
    def dados(self) -> Path:
        return self.base / "data"

    @property
    def inspecoes(self) -> Path:
        return self.dados / "inspecoes"

    @property
    def saida(self) -> Path:
        return self.base / "output"

    @property
    def api_json(self) -> Path:
        return self.saida / "api"

    @property
    def cache(self) -> Path:
        return self.saida / "cache"

    @property
    def outbox(self) -> Path:
        return self.saida / "outbox"

    @property
    def quarentena(self) -> Path:
        return self.saida / "quarentena"

    @property
    def banco(self) -> Path:
        return self.saida / "citizentech.db"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    def criar_pastas(self) -> None:
        for p in (self.saida, self.api_json, self.cache, self.outbox, self.quarentena, self.logs):
            p.mkdir(parents=True, exist_ok=True)


def carregar_config(caminhos: Caminhos) -> dict:
    if not caminhos.config.exists():
        raise ConfiguracaoInvalida(f"Arquivo de configuração não encontrado: {caminhos.config}")
    try:
        cfg = json.loads(caminhos.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfiguracaoInvalida(f"config.json inválido: {exc}") from exc
    faltando = [c for c in CAMPOS_OBRIGATORIOS if c not in cfg]
    if faltando:
        raise ConfiguracaoInvalida(f"Campos obrigatórios ausentes em config.json: {faltando}")
    return cfg
