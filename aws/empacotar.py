"""Empacota o código para a AWS Lambda (sem dependências externas - só biblioteca padrão + boto3 do runtime).

    python aws/empacotar.py

Gera:
  aws/dist/lambda/                  -> usado pelo SAM (CodeUri do template.yaml)
  aws/dist/boca-de-lobo-lambda.zip  -> para enviar pelo Console da AWS (Lambda > Upload from > .zip)
"""
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "aws" / "dist"
DESTINO = DIST / "lambda"
ITENS = ["src", "config", "data", "mvp"]

shutil.rmtree(DIST, ignore_errors=True)
for item in ITENS:
    shutil.copytree(RAIZ / item, DESTINO / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
# Ponto de entrada padrão do Lambda na raiz do pacote
(DESTINO / "lambda_function.py").write_text(
    '"""Ponto de entrada do AWS Lambda - o código real está em src/aws_lambda.py."""\n'
    "import os\nimport sys\n\n"
    'sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))\n\n'
    "from aws_lambda import handler_api, handler_bot  # noqa: E402,F401\n", encoding="utf-8")
zip_ = shutil.make_archive(str(DIST / "boca-de-lobo-lambda"), "zip", DESTINO)
tamanho = Path(zip_).stat().st_size / 1024
print(f"Pacote pronto: {DESTINO}\nZip para o console: {zip_} ({tamanho:.0f} KB)")
print("Handlers: lambda_function.handler_api  |  lambda_function.handler_bot")
