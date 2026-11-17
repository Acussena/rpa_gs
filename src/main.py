"""Ponto de entrada do bot. Agendado diariamente (Agendador de Tarefas do Windows / cron / GitHub Actions).

Exemplos:
    python src/main.py                       # previsão real (Open-Meteo)
    python src/main.py --simular-chuva 75    # cenário de chuva forte (demonstração)
    python src/main.py --simular-chuva 5     # cenário sem ação
    python src/main.py --falhar-api          # simula API fora do ar (usa cache ou falha controlada)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bocadelobo.bot import executar  # noqa: E402

BASE = Path(__file__).resolve().parent.parent


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="CitizenTech Boca de Lobo - bot RPA de prevenção de alagamentos")
    p.add_argument("--simular-chuva", type=float, metavar="MM", help="ignora a API e usa X mm previstos em 24h")
    p.add_argument("--falhar-api", action="store_true", help="simula indisponibilidade da API de previsão")
    p.add_argument("--base", type=Path, default=BASE, help="pasta base do projeto (config/, data/, output/, logs/)")
    a = p.parse_args()
    resumo = executar(a.base, simular_chuva=a.simular_chuva, falhar_api=a.falhar_api)
    print(f"\n==> {resumo['status']} | nível: {resumo.get('nivel', '-')} | "
          f"OS: {resumo['ordens_geradas']} | alertas: {resumo['alertas_enviados']} | "
          f"código de saída: {resumo['codigo_saida']}")
    return resumo["codigo_saida"]


if __name__ == "__main__":
    sys.exit(main())
