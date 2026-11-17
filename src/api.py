"""API REST do MVP CitizenTech que expõe o resultado do bot (consumida pelo dashboard e pelo app do cidadão).

    python src/api.py            -> http://localhost:8000

Endpoints:
    GET /api/status       última execução do bot
    GET /api/ordens       ordens de serviço (lista priorizada de bocas de lobo) da última execução
    GET /api/alertas      alertas vigentes no dia da última execução (contatos mascarados)
    GET /api/alertas/publico   alertas por área para o app do cidadão (sem dados pessoais)
    GET /api/execucoes    histórico de execuções (auditoria)
    GET /                 dashboard do MVP (mvp/index.html)
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bocadelobo.persistencia import Banco  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
BANCO = BASE / "output" / "citizentech.db"
DASHBOARD = BASE / "mvp" / "index.html"


def _alertas_publicos(alertas: list) -> list:
    por_area = {}
    for a in alertas:
        if a["publico"] == "morador" and a["area_id"] not in por_area:
            por_area[a["area_id"]] = {"area_id": a["area_id"], "nivel": a["nivel"], "mensagem": a["mensagem"],
                                      "emitido_em": a["criado_em"]}
    return list(por_area.values())


class Handler(BaseHTTPRequestHandler):
    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):  # noqa: N802
        rota = self.path.split("?")[0].rstrip("/") or "/"
        if rota == "/":
            corpo = DASHBOARD.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)
            return
        if not BANCO.exists():
            return self._json({"erro": "Bot ainda não foi executado"}, 404)
        banco = Banco(BANCO)
        ultima = banco.ultima_execucao()
        exec_id = ultima["id"] if ultima else None
        dia = ultima["inicio"][:10] if ultima else ""
        if rota == "/api/status":
            return self._json(ultima or {})
        if rota == "/api/ordens":
            return self._json(banco.ordens(exec_id) if exec_id else [])
        if rota == "/api/alertas":
            return self._json(banco.alertas_do_dia(dia) if exec_id else [])
        if rota == "/api/alertas/publico":
            return self._json(_alertas_publicos(banco.alertas_do_dia(dia)) if exec_id else [])
        if rota == "/api/execucoes":
            return self._json(banco.execucoes())
        return self._json({"erro": "rota não encontrada"}, 404)

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[api] {self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    import os
    porta = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8000))
    print(f"API CitizenTech Boca de Lobo em http://localhost:{porta}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", porta), Handler).serve_forever()
