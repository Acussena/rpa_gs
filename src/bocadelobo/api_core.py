"""Núcleo da API REST do Boca de Lobo - independente de onde roda.

O mesmo código atende:
  * localmente   -> src/api.py (servidor HTTP da biblioteca padrão, arquivos em disco)
  * na AWS       -> src/aws_lambda.py (API Gateway + Lambda, arquivos no S3)

A diferença é só o "armazenamento", que guarda os arquivos com a mesma estrutura de pastas do projeto
(data/..., output/..., logs/...).
"""
from __future__ import annotations

import csv
import hmac
import io
import json
import re
from datetime import datetime
from pathlib import Path

RESULTADO = "output/api/ultimo_resultado.json"
HISTORICO = "output/api/execucoes.json"
CAMPOS_INSPECAO = ["id_bueiro", "data_hora_inspecao", "nivel_obstrucao", "tipo_residuo", "confianca_visao", "foto_ref"]
OBRIGATORIOS_INSPECAO = ["id_bueiro", "data_hora_inspecao", "nivel_obstrucao"]
MAX_INSPECOES_POR_ENVIO = 500


class ArmazenamentoLocal:
    """Arquivos numa pasta do disco (a raiz do projeto)."""

    def __init__(self, base: Path):
        self.base = Path(base)

    def ler(self, chave: str) -> bytes | None:
        arq = self.base / chave
        return arq.read_bytes() if arq.exists() else None

    def gravar(self, chave: str, dados: bytes) -> None:
        arq = self.base / chave
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(dados)


class ErroApi(Exception):
    def __init__(self, status: int, mensagem: str, detalhes=None):
        super().__init__(mensagem)
        self.status, self.mensagem, self.detalhes = status, mensagem, detalhes


def _ler_json(armaz, chave, padrao):
    bruto = armaz.ler(chave)
    if bruto is None:
        return padrao
    try:
        return json.loads(bruto.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ErroApi(500, f"arquivo de resultado corrompido: {chave}") from exc


def _pacote(armaz) -> dict:
    p = _ler_json(armaz, RESULTADO, None)
    if p is None:
        raise ErroApi(404, "o bot ainda não foi executado - nenhum resultado disponível")
    return p


def _filtrar(itens: list, params: dict, campos: dict) -> list:
    """?prioridade=CRITICA&equipe=EQ-01&area=AR-01 (aceita valores separados por vírgula)."""
    for param, campo in campos.items():
        valor = (params.get(param) or "").strip()
        if valor:
            aceitos = {v.strip().upper() for v in valor.split(",")}
            itens = [i for i in itens if str(i.get(campo) or "").upper() in aceitos]
    return itens


def alertas_publicos(alertas: list) -> list:
    """Um alerta por área, sem nenhum dado pessoal - para o app do cidadão."""
    por_area = {}
    for a in alertas:
        if a.get("publico") == "morador" and a["area_id"] not in por_area:
            por_area[a["area_id"]] = {"area_id": a["area_id"], "nivel": a["nivel"], "mensagem": a["mensagem"],
                                      "emitido_em": a.get("criado_em")}
    return list(por_area.values())


def _autorizar(headers: dict, token: str | None) -> None:
    """Rotas de escrita exigem o cabeçalho x-api-key quando API_TOKEN está configurado."""
    if not token:
        return
    enviado = headers.get("x-api-key") or ""
    if not hmac.compare_digest(enviado, token):
        raise ErroApi(401, "x-api-key ausente ou inválida")


def _corpo_json(corpo: bytes | str | None) -> dict:
    if not corpo:
        return {}
    try:
        dados = json.loads(corpo)
    except ValueError as exc:
        raise ErroApi(400, "corpo da requisição não é um JSON válido") from exc
    if not isinstance(dados, dict):
        raise ErroApi(400, "o corpo deve ser um objeto JSON")
    return dados


def receber_inspecoes(armaz, dados: dict, agora: datetime) -> dict:
    """POST /api/inspecoes - o carrinho (robô) envia o resultado da ronda.
    Valida a estrutura e grava um CSV em data/inspecoes/; a validação de negócio completa (bueiro cadastrado,
    duplicidade, datas) é feita pelo bot na próxima execução, que põe em quarentena o que estiver errado."""
    robo = re.sub(r"[^A-Za-z0-9_-]", "", str(dados.get("robo_id") or "robo"))[:30] or "robo"
    lista = dados.get("inspecoes")
    if not isinstance(lista, list) or not lista:
        raise ErroApi(400, "envie 'inspecoes' como uma lista não vazia")
    if len(lista) > MAX_INSPECOES_POR_ENVIO:
        raise ErroApi(413, f"máximo de {MAX_INSPECOES_POR_ENVIO} inspeções por envio")
    erros = []
    for i, item in enumerate(lista):
        if not isinstance(item, dict):
            erros.append({"indice": i, "erro": "item não é um objeto"})
            continue
        faltando = [c for c in OBRIGATORIOS_INSPECAO if item.get(c) in (None, "")]
        if faltando:
            erros.append({"indice": i, "erro": f"campos obrigatórios ausentes: {faltando}"})
    if erros:
        raise ErroApi(422, "inspeções inválidas - nada foi gravado", erros)

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CAMPOS_INSPECAO, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for item in lista:
        w.writerow({c: item.get(c, "") for c in CAMPOS_INSPECAO})
    chave = f"data/inspecoes/{agora:%Y-%m-%d}_{robo}_{agora:%H%M%S}.csv"
    armaz.gravar(chave, buf.getvalue().encode("utf-8"))
    return {"recebidas": len(lista), "arquivo": chave,
            "mensagem": "inspeções recebidas; serão processadas na próxima execução do bot"}


def log_da_execucao(armaz, execucao_id: str | None) -> dict:
    """GET /api/log?execucao=EX... - linhas do log de auditoria de uma execução (padrão: a última).
    O log já é gravado sem dados pessoais (telefone/e-mail mascarados), então pode ser exibido no painel."""
    if not execucao_id:
        execucao_id = _pacote(armaz)["execucao"]["id"]
    m = re.fullmatch(r"EX(\d{8})T\d{6}", execucao_id or "")
    if not m:
        raise ErroApi(400, "execucao deve ter o formato EXAAAAMMDDTHHMMSS")
    bruto = armaz.ler(f"logs/bot_{m.group(1)}.jsonl")
    linhas = []
    for linha in (bruto or b"").decode("utf-8").splitlines():
        try:
            item = json.loads(linha)
        except ValueError:
            continue
        if item.get("execucao_id") == execucao_id:
            linhas.append({k: item.get(k) for k in ("data_hora", "nivel", "etapa", "mensagem")})
    if not linhas:
        raise ErroApi(404, f"nenhum registro de log para a execução {execucao_id}")
    return {"execucao_id": execucao_id, "linhas": linhas}


def tratar(metodo: str, rota: str, params: dict, corpo, headers: dict, armaz, *,
           executar_bot=None, token: str | None = None, agora: datetime | None = None,
           limpar_demo=None) -> tuple[int, object]:
    """Roteador: devolve (status_http, corpo_json)."""
    metodo = metodo.upper()
    rota = "/" + rota.strip("/")
    if rota.startswith("/api/") is False and rota != "/api":
        rota = "/api" + rota            # aceita /status e /api/status
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    params = params or {}
    try:
        if metodo == "GET":
            if rota in ("/api", "/api/saude"):
                return 200, {"servico": "CitizenTech Boca de Lobo", "status": "ok",
                             "rotas": ["GET /api/status", "GET /api/ordens", "GET /api/ordens/{id_bueiro}",
                                       "GET /api/alertas", "GET /api/alertas/publico", "GET /api/pendencias",
                                       "GET /api/execucoes", "GET /api/log", "POST /api/inspecoes",
                                       "POST /api/executar", "POST /api/demo/limpar"]}
            if rota == "/api/status":
                return 200, _pacote(armaz)["execucao"]
            if rota == "/api/ordens":
                ordens = _filtrar(_pacote(armaz)["ordens_servico"], params,
                                  {"prioridade": "prioridade", "equipe": "equipe_id", "area": "area_id",
                                   "status": "status"})
                return 200, ordens
            if rota.startswith("/api/ordens/"):
                bid = rota.rsplit("/", 1)[1].upper()
                for o in _pacote(armaz)["ordens_servico"]:
                    if o["id_bueiro"].upper() == bid:
                        return 200, o
                raise ErroApi(404, f"boca de lobo {bid} não está na lista de limpeza atual")
            if rota == "/api/alertas":
                return 200, _filtrar(_pacote(armaz)["alertas"], params, {"area": "area_id", "publico": "publico"})
            if rota == "/api/alertas/publico":
                return 200, _filtrar(alertas_publicos(_pacote(armaz)["alertas"]), params, {"area": "area_id"})
            if rota == "/api/pendencias":
                p = _pacote(armaz)
                return 200, {"bueiros_sem_inspecao": p.get("bueiros_sem_inspecao", []),
                             "aguardando_reforco": [o for o in p["ordens_servico"] if not o.get("equipe_id")],
                             "reinspecionar": [o for o in p["ordens_servico"] if o.get("reinspecionar")]}
            if rota == "/api/execucoes":
                return 200, _ler_json(armaz, HISTORICO, [])
            if rota == "/api/log":
                return 200, log_da_execucao(armaz, params.get("execucao"))
        elif metodo == "POST":
            if rota == "/api/inspecoes":
                _autorizar(headers, token)
                return 201, receber_inspecoes(armaz, _corpo_json(corpo), agora or datetime.now())
            if rota == "/api/executar":
                _autorizar(headers, token)
                if executar_bot is None:
                    raise ErroApi(501, "execução sob demanda não disponível neste ambiente")
                dados = _corpo_json(corpo)
                simular = dados.get("simular_chuva")
                if simular is not None:
                    try:
                        simular = float(simular)
                    except (TypeError, ValueError) as exc:
                        raise ErroApi(400, "simular_chuva deve ser numérico (mm em 24h)") from exc
                    if not 0 <= simular <= 500:
                        raise ErroApi(400, "simular_chuva deve estar entre 0 e 500 mm")
                resumo = executar_bot(simular_chuva=simular, falhar_api=bool(dados.get("falhar_api")))
                return (200 if resumo.get("codigo_saida") == 0 else 502), resumo
            if rota == "/api/demo/limpar":
                _autorizar(headers, token)
                if limpar_demo is None:
                    raise ErroApi(501, "limpeza da demonstração não disponível neste ambiente")
                return 200, limpar_demo()
        elif metodo == "OPTIONS":
            return 204, None
        raise ErroApi(404, f"rota não encontrada: {metodo} {rota}")
    except ErroApi as exc:
        corpo_erro = {"erro": exc.mensagem}
        if exc.detalhes:
            corpo_erro["detalhes"] = exc.detalhes
        return exc.status, corpo_erro
