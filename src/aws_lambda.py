"""Versão AWS do Boca de Lobo: duas funções Lambda que compartilham um bucket S3.

  handler_bot  -> agendada pelo EventBridge (todo dia 06:00): baixa os dados do S3 para /tmp, roda o bot e
                  devolve os resultados (banco, JSON, logs, quarentena, outbox) ao S3.
  handler_api  -> atrás do API Gateway (HTTP API): responde às rotas da API lendo os resultados do S3 e
                  recebe as inspeções que o carrinho envia (POST /api/inspecoes).

O bucket guarda os arquivos com a mesma estrutura de pastas do projeto:
  s3://<bucket>/data/inspecoes/*.csv      <- enviados pelo carrinho (via API ou upload direto)
  s3://<bucket>/data/*.json|csv           <- cadastros (criados automaticamente na 1ª execução)
  s3://<bucket>/output/api/*.json         <- resultado lido pela API
  s3://<bucket>/output/citizentech.db     <- banco (histórico e idempotência dos alertas)
  s3://<bucket>/logs/*.jsonl              <- logs de auditoria

Variáveis de ambiente: BUCKET (obrigatória), API_TOKEN (opcional, protege as rotas POST), TZ=America/Sao_Paulo.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
from pathlib import Path

PACOTE = Path(__file__).resolve().parent.parent            # raiz do pacote (config/, data/, mvp/, src/)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bocadelobo.api_core import tratar  # noqa: E402
from bocadelobo.bot import executar  # noqa: E402

TMP = Path(os.environ.get("BOCADELOBO_TMP", "/tmp/bocadelobo"))
_cliente = None


def cliente_s3():
    global _cliente
    if _cliente is None:
        import boto3  # já vem no runtime Python do Lambda
        _cliente = boto3.client("s3")
    return _cliente


class ArmazenamentoS3:
    def __init__(self, bucket: str, s3=None):
        self.bucket = bucket
        self.s3 = s3 or cliente_s3()

    def ler(self, chave: str) -> bytes | None:
        try:
            return self.s3.get_object(Bucket=self.bucket, Key=chave)["Body"].read()
        except self.s3.exceptions.NoSuchKey:
            return None

    def gravar(self, chave: str, dados: bytes) -> None:
        tipo = "application/json" if chave.endswith(".json") else "text/plain; charset=utf-8"
        self.s3.put_object(Bucket=self.bucket, Key=chave, Body=dados, ContentType=tipo)

    def listar(self, prefixo: str) -> list:
        chaves, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefixo}
            if token:
                kw["ContinuationToken"] = token
            resp = self.s3.list_objects_v2(**kw)
            chaves += [o["Key"] for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return chaves
            token = resp["NextContinuationToken"]


def executar_no_s3(armaz: ArmazenamentoS3, **opcoes) -> dict:
    """S3 -> /tmp -> bot -> S3. O bot em si é exatamente o mesmo que roda localmente."""
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True)
    shutil.copytree(PACOTE / "config", TMP / "config")

    if not armaz.listar("data/"):                          # 1ª execução: semeia o bucket com os cadastros
        for arq in (PACOTE / "data").rglob("*"):
            if arq.is_file():
                armaz.gravar(arq.relative_to(PACOTE).as_posix(), arq.read_bytes())
    for prefixo in ("config/", "data/", "output/", "logs/"):
        for chave in armaz.listar(prefixo):
            if chave.endswith("/"):
                continue
            destino = TMP / chave
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(armaz.ler(chave) or b"")

    resumo = executar(TMP, **opcoes)

    for pasta in ("output", "logs"):
        for arq in (TMP / pasta).rglob("*"):
            if arq.is_file():
                armaz.gravar(arq.relative_to(TMP).as_posix(), arq.read_bytes())
    return resumo


def _armaz():
    bucket = os.environ.get("BUCKET")
    if not bucket:
        raise RuntimeError("variável de ambiente BUCKET não configurada")
    return ArmazenamentoS3(bucket)


def handler_bot(event, context=None):
    """EventBridge (agendado) ou invocação manual com {"simular_chuva": 75}."""
    event = event if isinstance(event, dict) else {}
    resumo = executar_no_s3(_armaz(), simular_chuva=event.get("simular_chuva"),
                            falhar_api=bool(event.get("falhar_api")))
    print(json.dumps({k: resumo.get(k) for k in ("id", "status", "nivel", "ordens_geradas", "alertas_enviados",
                                                   "codigo_saida")}, ensure_ascii=False))
    return resumo


def handler_api(event, context=None, armaz=None):
    """API Gateway HTTP API (payload 2.0) - também aceita o formato 1.0 (REST API)."""
    armaz = armaz or _armaz()
    if "requestContext" in event and "http" in event["requestContext"]:
        metodo, rota = event["requestContext"]["http"]["method"], event.get("rawPath", "/")
    else:
        metodo, rota = event.get("httpMethod", "GET"), event.get("path", "/")
    corpo = event.get("body")
    if corpo and event.get("isBase64Encoded"):
        corpo = base64.b64decode(corpo)

    if metodo == "GET" and rota in ("", "/", "/index.html"):
        return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8"},
                "body": (PACOTE / "mvp" / "index.html").read_text(encoding="utf-8")}

    status, dados = tratar(metodo, rota, event.get("queryStringParameters") or {}, corpo,
                           event.get("headers") or {}, armaz,
                           executar_bot=lambda **kw: executar_no_s3(armaz, **kw),
                           token=os.environ.get("API_TOKEN"))
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "content-type, x-api-key",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS"},
        "body": "" if dados is None else json.dumps(dados, ensure_ascii=False, default=str),
    }
