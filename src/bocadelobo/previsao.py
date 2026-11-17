"""Consulta da previsão de chuva (Open-Meteo) com retentativas, validação e cache de contingência."""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from .config import Caminhos


class PrevisaoIndisponivel(Exception):
    """API fora do ar e nenhum cache válido: o bot não pode decidir com segurança."""


class RespostaInvalida(Exception):
    """A API respondeu, mas com conteúdo fora do formato esperado."""


@dataclass
class Previsao:
    fonte: str              # "open-meteo", "cache", "simulacao"
    consultada_em: str
    chuva_24h_mm: float
    pico_mm_h: float
    probabilidade_max_pct: float
    horas_com_chuva: int

    def to_dict(self) -> dict:
        return asdict(self)


def montar_url(cfg: dict) -> str:
    params = {
        "latitude": cfg["latitude"],
        "longitude": cfg["longitude"],
        "hourly": "precipitation,precipitation_probability",
        "forecast_days": 2,
        "timezone": cfg.get("fuso_horario", "America/Sao_Paulo"),
    }
    return f"{cfg['api_previsao']['url']}?{urllib.parse.urlencode(params)}"


def interpretar_resposta(dados: dict, agora: datetime) -> Previsao:
    """Recorta as próximas 24h da série horária e calcula total, pico e probabilidade."""
    try:
        horas = dados["hourly"]["time"]
        chuva = dados["hourly"]["precipitation"]
        prob = dados["hourly"].get("precipitation_probability") or [None] * len(horas)
    except (KeyError, TypeError) as exc:
        raise RespostaInvalida(f"campo ausente na resposta: {exc}") from exc
    if not (len(horas) == len(chuva) == len(prob)):
        raise RespostaInvalida("séries horárias com tamanhos diferentes")

    inicio = agora.replace(minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(hours=24)
    total, pico, pmax, horas_chuva, n = 0.0, 0.0, 0.0, 0, 0
    for h, mm, p in zip(horas, chuva, prob):
        try:
            t = datetime.fromisoformat(h)
        except ValueError as exc:
            raise RespostaInvalida(f"horário inválido: {h}") from exc
        if not (inicio <= t < fim):
            continue
        n += 1
        mm = float(mm or 0)
        if mm < 0:
            raise RespostaInvalida(f"precipitação negativa em {h}")
        total += mm
        pico = max(pico, mm)
        pmax = max(pmax, float(p or 0))
        horas_chuva += 1 if mm >= 0.5 else 0
    if n < 12:
        raise RespostaInvalida(f"apenas {n} horas de previsão disponíveis (mínimo 12)")
    return Previsao("open-meteo", agora.isoformat(timespec="seconds"),
                    round(total, 1), round(pico, 1), pmax, horas_chuva)


def previsao_simulada(mm: float, agora: datetime) -> Previsao:
    """Cenário controlado para demonstração e testes (ex.: --simular-chuva 75)."""
    return Previsao("simulacao", agora.isoformat(timespec="seconds"), float(mm),
                    round(mm * 0.3, 1), 90.0 if mm > 0 else 5.0, min(24, int(mm // 4)))


def _salvar_cache(caminhos: Caminhos, prev: Previsao) -> None:
    caminhos.cache.mkdir(parents=True, exist_ok=True)
    (caminhos.cache / "previsao_cache.json").write_text(
        json.dumps(prev.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def _ler_cache(caminhos: Caminhos, agora: datetime, validade_h: float, log) -> Previsao | None:
    arq = caminhos.cache / "previsao_cache.json"
    if not arq.exists():
        log.aviso("previsao", "Nenhum cache de previsão disponível")
        return None
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
        idade = agora - datetime.fromisoformat(d["consultada_em"])
        prev = Previsao(**d)
    except (ValueError, KeyError, TypeError) as exc:
        log.erro("previsao", f"Cache de previsão corrompido: {exc}")
        return None
    horas = idade.total_seconds() / 3600
    if horas > validade_h:
        log.aviso("previsao", f"Cache expirado ({horas:.1f}h > {validade_h}h) - descartado")
        return None
    prev.fonte = f"cache ({horas:.1f}h atrás)"
    return prev


def buscar_previsao(cfg: dict, caminhos: Caminhos, agora: datetime, log, *,
                    simular_mm: float | None = None, forcar_falha: bool = False,
                    abrir_url=urllib.request.urlopen, dormir=time.sleep) -> Previsao:
    if simular_mm is not None:
        prev = previsao_simulada(simular_mm, agora)
        log.info("previsao", f"Modo simulação: {simular_mm} mm em 24h", prev.to_dict())
        return prev

    api = cfg["api_previsao"]
    url = montar_url(cfg)
    tentativas = int(api.get("tentativas", 3))
    for t in range(1, tentativas + 1):
        try:
            if forcar_falha:
                raise urllib.error.URLError("falha simulada (--falhar-api)")
            with abrir_url(url, timeout=api.get("timeout_s", 10)) as resp:
                if getattr(resp, "status", 200) != 200:
                    raise urllib.error.HTTPError(url, resp.status, "status inesperado", None, None)
                dados = json.loads(resp.read().decode("utf-8"))
            prev = interpretar_resposta(dados, agora)
            _salvar_cache(caminhos, prev)
            log.info("previsao", f"Previsão obtida na tentativa {t}/{tentativas}", prev.to_dict())
            return prev
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError,
                json.JSONDecodeError, UnicodeDecodeError, RespostaInvalida) as exc:
            log.aviso("previsao", f"Tentativa {t}/{tentativas} falhou: {type(exc).__name__}: {exc}")
            if t < tentativas:
                espera = api.get("backoff_s", 1) * (2 ** (t - 1))
                dormir(espera)

    log.aviso("previsao", "API indisponível após todas as tentativas - acionando contingência (cache)")
    prev = _ler_cache(caminhos, agora, cfg.get("cache_previsao_validade_horas", 24), log)
    if prev:
        log.info("previsao", f"Usando previsão em cache: {prev.fonte}", prev.to_dict())
        return prev
    raise PrevisaoIndisponivel("API de previsão fora do ar e sem cache válido")
