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
    GET  /api/log?execucao=EX...     log de auditoria de uma execução (padrão: a última)
    POST /api/inspecoes              o carrinho/robô envia o resultado da ronda      [x-api-key]
    POST /api/executar               dispara o bot agora {"simular_chuva": 75}       [x-api-key]
                                     ou simula a API de previsão fora do ar {"falhar_api": true}
    POST /api/demo/limpar            apaga resultados e logs para recomeçar a demonstração (só local) [x-api-key]

Variável opcional API_TOKEN: se definida, as rotas POST exigem o cabeçalho x-api-key.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime
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


_ultima = {"inicio": None}


def executar_bot(**kw):
    with TRAVA:
        # o id da execução tem resolução de segundos: garante ids distintos em cliques seguidos no painel
        while _ultima["inicio"] == datetime.now().replace(microsecond=0):
            time.sleep(0.1)
        _ultima["inicio"] = datetime.now().replace(microsecond=0)
        return executar(BASE, agora=_ultima["inicio"], console=False, **kw)


def limpar_demo():
    """Recomeça a demonstração: apaga resultados, banco e logs (mantém o cache da previsão,
    usado para mostrar a recuperação quando a API de previsão cai)."""
    with TRAVA:
        apagados = 0
        for pasta in (BASE / "output", BASE / "logs"):
            if not pasta.exists():
                continue
            for item in pasta.iterdir():
                if item.name == "cache":
                    continue
                shutil.rmtree(item) if item.is_dir() else item.unlink()
                apagados += 1
        return {"mensagem": "Demonstração reiniciada: resultados e logs apagados (cache da previsão mantido)",
                "itens_apagados": apagados}


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
                               ARMAZ, executar_bot=executar_bot, limpar_demo=limpar_demo,
                               token=os.environ.get("API_TOKEN"))
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
    porta = int(os.environ.get("PORT") or next((a for a in sys.argv[1:] if a.isdigit()), 8000))
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    print(f"Painel e API CitizenTech Boca de Lobo em http://localhost:{porta}  (feche esta janela para encerrar)",
          flush=True)
    if "--abrir" in sys.argv:
        webbrowser.open(f"http://localhost:{porta}")
    servidor.serve_forever()
