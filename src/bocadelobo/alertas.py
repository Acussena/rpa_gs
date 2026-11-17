"""Montagem e disparo de alertas (moradores, equipes de limpeza e operação), com idempotência e LGPD."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

from .log_utils import mascarar_email, mascarar_telefone

ROTULO_NIVEL = {"ATENCAO": "ATENÇÃO", "ALERTA": "ALERTA"}


def chave(*partes) -> str:
    return hashlib.sha256("|".join(map(str, partes)).encode()).hexdigest()[:20]


def _destino_mascarado(m: dict) -> str:
    return mascarar_email(m["email"]) if m["canal"] == "email" else mascarar_telefone(m["telefone"])


def montar_alertas_moradores(areas_alvo: list, lista: list, areas: dict, moradores: list,
                             prev, nivel: str, cfg: dict, execucao_id: str, data: str, log) -> list:
    alertas, sem_consentimento = [], 0
    for aid in areas_alvo:                                        # loop por área em risco
        criticos = [i for i in lista if i["area_id"] == aid and i["prioridade"] in ("CRITICA", "ALTA")][:3]
        evitar = ", ".join(i["endereco"].split(",")[0] for i in criticos) or "vias baixas e próximas a córregos"
        msg = (f"[CitizenTech] {ROTULO_NIVEL[nivel]} de chuva forte em {areas[aid]['nome']}: "
               f"previsão de {prev.chuva_24h_mm:.0f} mm nas próximas 24h. "
               f"Evite passar por: {evitar} (bocas de lobo obstruídas, risco de alagamento). "
               f"Equipes de limpeza já foram acionadas. Emergência: {cfg.get('contatos_emergencia', '199')}.")
        for m in moradores:                                       # loop por morador inscrito
            if m["area_id"] != aid:
                continue
            if m.get("consentimento_lgpd", "").strip().lower() != "sim":
                sem_consentimento += 1                            # LGPD: só envia com consentimento
                continue
            alertas.append({
                "chave_idempotencia": chave(data, "morador", m["id_morador"], aid, nivel),
                "execucao_id": execucao_id, "publico": "morador", "destinatario_id": m["id_morador"],
                "destino_mascarado": _destino_mascarado(m), "canal": m["canal"], "area_id": aid,
                "nivel": nivel, "mensagem": msg,
            })
    if sem_consentimento:
        log.info("alertas", f"{sem_consentimento} morador(es) sem consentimento LGPD não serão notificados")
    return alertas


def montar_alertas_equipes(atribuidos: list, equipes: list, nivel: str, execucao_id: str, data: str) -> list:
    alertas = []
    for e in equipes:
        itens = [i for i in atribuidos if i["equipe_id"] == e["id"]]
        if not itens:
            continue
        roteiro = " | ".join(f"{i['ordem']}. {i['id_bueiro']} {i['endereco']} ({i['prioridade']}, "
                             f"{i['nivel_obstrucao']:.0f}% obstruído)" for i in itens)
        alertas.append({
            "chave_idempotencia": chave(data, "equipe", e["id"], nivel, ",".join(i["id_bueiro"] for i in itens)),
            "execucao_id": execucao_id, "publico": "equipe_limpeza", "destinatario_id": e["id"],
            "destino_mascarado": e["nome"], "canal": "app_equipe", "area_id": None, "nivel": nivel,
            "mensagem": f"Ordem de serviço {ROTULO_NIVEL[nivel]} - limpar antes da chuva: {roteiro}",
        })
    return alertas


def _post_webhook(url: str, texto: str, tentativas: int = 3, dormir=time.sleep) -> None:
    corpo = {"content": texto[:1900]} if "discord" in url else {"text": texto}
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"})
    ultimo = None
    for t in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(req, timeout=10):
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            ultimo = exc
            if t < tentativas:
                dormir(2 ** (t - 1))
    raise ConnectionError(f"webhook falhou após {tentativas} tentativas: {ultimo}")


def despachar(alertas: list, banco, pasta_outbox, log, agora: datetime) -> dict:
    """Entrega no gateway (outbox JSONL simulando SMS/WhatsApp/e-mail) sem reenviar duplicados."""
    stats = {"enviados": 0, "ignorados_duplicados": 0, "falhas": 0}
    pasta_outbox.mkdir(parents=True, exist_ok=True)
    arq = pasta_outbox / f"outbox_{agora:%Y%m%d}.jsonl"
    for a in alertas:
        if banco.alerta_ja_enviado(a["chave_idempotencia"]):
            stats["ignorados_duplicados"] += 1
            continue
        try:
            a["criado_em"] = agora.isoformat(timespec="seconds")
            with arq.open("a", encoding="utf-8") as f:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
            banco.registrar_alerta(a)
            stats["enviados"] += 1
        except OSError as exc:
            stats["falhas"] += 1
            log.erro("alertas", f"Falha ao enfileirar alerta para {a['destinatario_id']}: {exc}")
    log.info("alertas", f"{stats['enviados']} alerta(s) enviado(s), "
                        f"{stats['ignorados_duplicados']} já enviado(s) hoje (idempotência), {stats['falhas']} falha(s)",
             stats)
    return stats


def notificar_operacao(texto: str, log, pasta_outbox, agora: datetime) -> bool:
    """Canal da operação (Defesa Civil/Subprefeitura). Webhook opcional via ALERTA_WEBHOOK_URL."""
    pasta_outbox.mkdir(parents=True, exist_ok=True)
    with (pasta_outbox / f"operacao_{agora:%Y%m%d}.log").open("a", encoding="utf-8") as f:
        f.write(f"{agora.isoformat(timespec='seconds')} {texto}\n")
    url = os.environ.get("ALERTA_WEBHOOK_URL")
    if not url:
        log.info("notificacao", "Resumo registrado no canal da operação (webhook não configurado)")
        return True
    try:
        _post_webhook(url, texto)
        log.info("notificacao", "Resumo enviado ao webhook da operação")
        return True
    except ConnectionError as exc:
        log.erro("notificacao", f"Falha no webhook da operação: {exc}")
        return False
