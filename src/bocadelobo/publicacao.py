"""Publicação automática do resultado no Amazon S3 (pasta de ingestão do MVP).

Ao fim de cada execução, o bot junta o resultado (output/api/ultimo_resultado.json) e o histórico
(output/api/execucoes.json) num único arquivo e o envia:
    output/publicado/bocaLobo_AAAAMMDD_HHMMSS.json  ->  s3://<bucket>/<prefixo>bocaLobo_AAAAMMDD_HHMMSS.json
DATA_HORA = início da execução. Cada execução gera um arquivo novo (nada é sobrescrito).

Configuração em config/config.json -> "publicacao_s3". Credenciais: as do ambiente (aws configure,
variáveis AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY ou role da AWS) - nunca no código.
Usa o boto3 se estiver instalado; senão, a AWS CLI. Desligar sem mexer no config: PUBLICAR_S3=0.

Uma falha de envio NÃO derruba o bot: é registrada no log, entra no resumo e a operação é avisada.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

PREFIXO_NOME = "bocaLobo"
CAMINHOS_CLI = [r"C:\Program Files\Amazon\AWSCLIV2\aws.exe", "/usr/local/bin/aws", "/usr/bin/aws"]


class FalhaPublicacao(Exception):
    pass


def _md5(dados: bytes) -> str:
    return hashlib.md5(dados).hexdigest()  # noqa: S324 - usado só para conferir integridade (ETag do S3)


def enviar_boto3(bucket: str, chave: str, dados: bytes, regiao: str) -> str:
    import boto3
    resp = boto3.client("s3", region_name=regiao).put_object(
        Bucket=bucket, Key=chave, Body=dados, ContentType="application/json")
    return resp["ETag"].strip('"')


def enviar_cli(bucket: str, chave: str, dados: bytes, regiao: str, arquivo: Path) -> str:
    aws = shutil.which("aws") or next((c for c in CAMINHOS_CLI if Path(c).exists()), None)
    if not aws:
        raise FalhaPublicacao("nem boto3 nem AWS CLI disponíveis para enviar ao S3")
    proc = subprocess.run([aws, "s3api", "put-object", "--bucket", bucket, "--key", chave, "--body", str(arquivo),
                           "--content-type", "application/json", "--region", regiao, "--output", "json"],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise FalhaPublicacao((proc.stderr or proc.stdout).strip().splitlines()[-1][:300])
    return json.loads(proc.stdout)["ETag"].strip('"')


def _escolher_enviador():
    try:
        import boto3  # noqa: F401
        return lambda b, k, d, r, arq: enviar_boto3(b, k, d, r)
    except ImportError:
        return enviar_cli


def montar_arquivo(pasta_api: Path, carimbo: datetime) -> Path:
    """Junta resultado + histórico num único arquivo bocaLobo_AAAAMMDD_HHMMSS.json (padrão de nomes do MVP)."""
    pacote = json.loads((pasta_api / "ultimo_resultado.json").read_text(encoding="utf-8"))
    hist = pasta_api / "execucoes.json"
    pacote["historico_execucoes"] = json.loads(hist.read_text(encoding="utf-8")) if hist.exists() else []
    destino = pasta_api.parent / "publicado" / f"{PREFIXO_NOME}_{carimbo:%Y%m%d_%H%M%S}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(pacote, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return destino


def publicar(cfg_pub: dict, pasta_api: Path, log, *, carimbo: datetime | None = None, enviar=None,
             dormir=time.sleep) -> dict:
    """Monta bocaLobo_<data>_<hora>.json, envia e confere a integridade (ETag == MD5).
    Retorna {"status", "enviados", "erro"}."""
    if os.environ.get("PUBLICAR_S3", "").strip() == "0" or not cfg_pub or not cfg_pub.get("ativo"):
        return {"status": "DESATIVADA", "enviados": []}
    bucket = cfg_pub.get("bucket")
    if not bucket:
        log.erro("publicacao", "publicacao_s3 ativa, mas sem 'bucket' configurado")
        return {"status": "FALHA", "enviados": [], "erro": "bucket não configurado"}
    if not (pasta_api / "ultimo_resultado.json").exists():
        log.aviso("publicacao", "ultimo_resultado.json não existe - nada a publicar")
        return {"status": "FALHA", "enviados": [], "erro": "resultado não gerado"}
    prefixo = cfg_pub.get("prefixo", "rpa/")
    prefixo = prefixo if not prefixo or prefixo.endswith("/") else prefixo + "/"
    regiao = cfg_pub.get("regiao", "us-east-1")
    tentativas = int(cfg_pub.get("tentativas", 3))
    enviar = enviar or _escolher_enviador()

    arq = montar_arquivo(pasta_api, carimbo or datetime.now())
    dados, chave = arq.read_bytes(), f"{prefixo}{arq.name}"
    ultimo_erro = None
    for t in range(1, tentativas + 1):
        try:
            etag = enviar(bucket, chave, dados, regiao, arq)
            if etag != _md5(dados):
                raise FalhaPublicacao(f"integridade: ETag {etag} diferente do MD5 local")
            log.info("publicacao", f"Publicado s3://{bucket}/{chave} ({len(dados)} bytes, integridade ok)")
            return {"status": "OK", "enviados": [f"s3://{bucket}/{chave}"]}
        except Exception as exc:  # noqa: BLE001 - qualquer erro de rede/permissão vira retentativa
            ultimo_erro = f"{type(exc).__name__}: {exc}"
            log.aviso("publicacao", f"Tentativa {t}/{tentativas} de enviar {chave} falhou: {ultimo_erro}")
            if t < tentativas:
                dormir(2 ** (t - 1))
    log.erro("publicacao", f"Não foi possível publicar {chave} no S3: {ultimo_erro}")
    return {"status": "FALHA", "enviados": [], "erro": ultimo_erro}
