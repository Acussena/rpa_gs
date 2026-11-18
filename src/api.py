"""API REST do MVP rodando localmente (mesmo código da versão AWS - ver src/aws_lambda.py).

    python src/api.py            -> http://localhost:8000      (dashboard em / e API em /api/...)

Rotas (documentação completa em docs/openapi.yaml):
    GET  /api/status                 última execução do bot
    GET  /api/ordens                 lista priorizada de bocas de lobo (?prioridade=&equipe=&area=&status=)
    GET  /api/ordens/{id_bueiro}     uma ordem de serviço
    GET  /api/alertas                alertas do dia (contatos mascarados) (?area=&publico=)
    GET  /api/alertas/publico        alertas por área, sem dados pessoais (app do cidadão)
    GET  /api/pendencias             bueiros sem inspeção, aguardando reforço, a reinspecionar
    GET  /api/execucoes              histórico de execuções (auditoria)
    POST /api/inspecoes              o carrinho/robô envia o resultado da ronda      [x-api-key]
    POST /api/executar               dispara o bot agora {"simular_chuva": 75}       [x-api-key]

Variável opcional API_TOKEN: se definida, as rotas POST exigem o cabeçalho x-api-key.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bocadelobo.api_core import ArmazenamentoLocal, tratar  # noqa: E402
from bocadelobo.bot import executar  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
DASHBOARD = BASE / "mvp" / "index.html"
ARMAZ = ArmazenamentoLocal(BASE)
TRAVA = threading.Lock()          # uma execução do bot por vez


def executar_bot(**kw):
    with TRAVA:
        return executar(BASE, **kw)


class Handler(BaseHTTPRequestHandler):
    def _responder(self, metodo):
        url = urlsplit(self.path)
        if metodo == "GET" and url.path in ("", "/", "/index.html"):
            corpo = DASHBOARD.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo_req = self.rfile.read(tamanho) if tamanho else None
        status, dados = tratar(metodo, url.path, dict(parse_qsl(url.query)), corpo_req, dict(self.headers),
                               ARMAZ, executar_bot=executar_bot, token=os.environ.get("API_TOKEN"))
        corpo = b"" if dados is None else json.dumps(dados, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type, x-api-key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):  # noqa: N802
        self._responder("GET")

    def do_POST(self):  # noqa: N802
        self._responder("POST")

    def do_OPTIONS(self):  # noqa: N802
        self._responder("OPTIONS")

    def log_message(self, fmt, *args):
        sys.stdout.write(f"[api] {self.address_string()} {fmt % args}\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    porta = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8000))
    print(f"API CitizenTech Boca de Lobo em http://localhost:{porta}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", porta), Handler).serve_forever()
