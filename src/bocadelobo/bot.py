"""Orquestrador do processo: previsão -> decisão -> inspeções -> priorização -> MVP -> alertas -> auditoria."""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path

from . import alertas as al
from . import dados, regras
from .config import Caminhos, ConfiguracaoInvalida, carregar_config
from .log_utils import Auditoria
from .persistencia import Banco, exportar_arquivos
from .previsao import PrevisaoIndisponivel, buscar_previsao
from .publicacao import publicar

# Códigos de saída (permitem ao agendador detectar falhas - nada de falha silenciosa)
OK, ERRO_INESPERADO, ERRO_PREVISAO, ERRO_DADOS = 0, 1, 2, 3


def executar(base: Path, *, agora: datetime | None = None, simular_chuva: float | None = None,
             falhar_api: bool = False, console: bool = True, dormir=None) -> dict:
    agora = agora or datetime.now()
    execucao_id = f"EX{agora:%Y%m%dT%H%M%S}"
    caminhos = Caminhos(Path(base))
    caminhos.criar_pastas()
    log = Auditoria(caminhos.logs, execucao_id, console=console)
    resumo = {"id": execucao_id, "inicio": agora.isoformat(timespec="seconds"), "status": "EM_EXECUCAO",
              "ordens_geradas": 0, "excedentes": 0, "alertas_enviados": 0, "alertas_ignorados": 0,
              "falhas_envio": 0, "linhas_lidas": 0, "inspecoes_validas": 0, "rejeitados": 0,
              "duplicados": 0, "arquivos_invalidos": 0}
    banco = None
    log.info("inicio", f"Execução {execucao_id} iniciada")
    try:
        cfg = carregar_config(caminhos)
        banco = Banco(caminhos.banco)

        # 1. Previsão do tempo (com retentativa e cache)
        kwargs = {"simular_mm": simular_chuva, "forcar_falha": falhar_api}
        if dormir:
            kwargs["dormir"] = dormir
        prev = buscar_previsao(cfg, caminhos, agora, log, **kwargs)
        resumo.update(fonte_previsao=prev.fonte, chuva_24h_mm=prev.chuva_24h_mm, pico_mm_h=prev.pico_mm_h,
                      probabilidade_max_pct=prev.probabilidade_max_pct)

        # 2. DECISÃO: a chuva justifica agir?
        nivel, justificativa = regras.classificar_nivel(prev, cfg["limites_chuva"])
        resumo.update(nivel=nivel, justificativa=justificativa)
        log.info("decisao", f"Nível {nivel}: {justificativa}")
        if nivel == regras.NORMAL:
            resumo.update(status="SEM_ACAO", mensagem="Chuva abaixo do limite - nenhuma ação necessária")
            return _finalizar(resumo, banco, log, caminhos, OK, dormir=dormir)

        # 3. Fontes de dados
        areas = dados.carregar_areas(caminhos)
        cadastro = dados.carregar_cadastro(caminhos, areas)
        insp = dados.carregar_inspecoes(caminhos, cadastro, agora, log)
        moradores = dados.carregar_moradores(caminhos, log)
        resumo.update(linhas_lidas=insp.linhas_lidas, inspecoes_validas=len(insp.validas),
                      rejeitados=len(insp.rejeitados), duplicados=insp.duplicados,
                      arquivos_invalidos=len(insp.arquivos_invalidos))
        _gravar_quarentena(caminhos, execucao_id, insp)

        # 4. Priorização (loop por bueiro) e distribuição às equipes
        lista, sem_inspecao = regras.priorizar(insp.validas, cadastro, areas, cfg, nivel, agora, log)
        atribuidos, excedentes = regras.distribuir_equipes(lista, cfg["equipes_limpeza"])
        ordens = atribuidos + excedentes
        resumo.update(ordens_geradas=len(ordens), excedentes=len(excedentes))
        log.info("priorizacao", f"{len(ordens)} ordem(ns) de serviço: "
                                f"{sum(o['prioridade'] == 'CRITICA' for o in ordens)} crítica(s), "
                                f"{sum(o['prioridade'] == 'ALTA' for o in ordens)} alta(s), "
                                f"{sum(o['prioridade'] == 'MEDIA' for o in ordens)} média(s)")
        if excedentes:
            log.aviso("priorizacao", f"Capacidade das equipes esgotada: {len(excedentes)} bueiro(s) "
                                     f"aguardando reforço: {', '.join(o['id_bueiro'] for o in excedentes)}")
        if sem_inspecao:
            log.aviso("priorizacao", f"{len(sem_inspecao)} bueiro(s) sem inspeção válida - "
                                     f"solicitar nova ronda do robô: {', '.join(s['id_bueiro'] for s in sem_inspecao)}")

        # 5. Integração com o MVP (banco + JSON/CSV)
        banco.salvar_ordens(execucao_id, ordens)

        # 6. Alertas: equipes + moradores das áreas em risco (DECISÃO por área)
        alvo = regras.areas_para_alerta(lista, areas, nivel)
        log.info("alertas", f"Áreas que receberão alerta: {', '.join(areas[a]['nome'] for a in alvo) or 'nenhuma'}")
        data = agora.strftime("%Y-%m-%d")
        lote = (al.montar_alertas_equipes(atribuidos, cfg["equipes_limpeza"], nivel, execucao_id, data)
                + al.montar_alertas_moradores(alvo, lista, areas, moradores, prev, nivel, cfg,
                                              execucao_id, data, log))
        stats = al.despachar(lote, banco, caminhos.outbox, log, agora)
        resumo.update(alertas_enviados=stats["enviados"], alertas_ignorados=stats["ignorados_duplicados"],
                      falhas_envio=stats["falhas"])

        texto_op = (f"[Boca de Lobo] {nivel} - {prev.chuva_24h_mm:.0f} mm previstos. {len(ordens)} OS geradas "
                    f"({len(excedentes)} aguardando reforço), {stats['enviados']} alertas enviados. "
                    f"Áreas: {', '.join(areas[a]['nome'] for a in alvo) or '-'}.")
        if not al.notificar_operacao(texto_op, log, caminhos.outbox, agora):
            resumo["falhas_envio"] += 1

        status = "CONCLUIDO_COM_PENDENCIAS" if (excedentes or stats["falhas"] or insp.rejeitados) else "CONCLUIDO"
        resumo.update(status=status, mensagem=texto_op)
        return _finalizar(resumo, banco, log, caminhos, OK, ordens=ordens, sem_inspecao=sem_inspecao,
                          dormir=dormir)

    except PrevisaoIndisponivel as exc:
        return _falha(resumo, banco, log, caminhos, agora, "FALHA_PREVISAO", str(exc), ERRO_PREVISAO, dormir)
    except (dados.DadosIndisponiveis, ConfiguracaoInvalida) as exc:
        return _falha(resumo, banco, log, caminhos, agora, "FALHA_DADOS", str(exc), ERRO_DADOS, dormir)
    except Exception as exc:  # noqa: BLE001 - última barreira: registra e devolve código de erro
        log.erro("erro", f"Erro inesperado: {type(exc).__name__}: {exc}", exc=True)
        return _falha(resumo, banco, log, caminhos, agora, "FALHA", f"{type(exc).__name__}: {exc}",
                      ERRO_INESPERADO)


def _gravar_quarentena(caminhos: Caminhos, execucao_id: str, insp) -> None:
    itens = insp.rejeitados + [{"arquivo": a["arquivo"], "linha": "-", "id_bueiro": "-", "motivo": a["motivo"]}
                               for a in insp.arquivos_invalidos]
    if not itens:
        return
    arq = caminhos.quarentena / f"rejeitados_{execucao_id}.csv"
    with arq.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["arquivo", "linha", "id_bueiro", "motivo"], delimiter=";")
        w.writeheader()
        w.writerows(itens)


def _falha(resumo, banco, log, caminhos, agora, status, msg, codigo, dormir=None):
    resumo.update(status=status, mensagem=msg)
    log.erro("falha", f"Execução interrompida de forma controlada: {msg}")
    al.notificar_operacao(f"[Boca de Lobo] FALHA ({status}): {msg} - verificação manual necessária.",
                          log, caminhos.outbox, agora)
    return _finalizar(resumo, banco, log, caminhos, codigo, dormir=dormir)


def _finalizar(resumo, banco, log, caminhos, codigo, ordens=None, sem_inspecao=None, dormir=None):
    resumo["fim"] = datetime.now().isoformat(timespec="seconds")
    resumo["codigo_saida"] = codigo
    try:
        historico, alertas = [resumo], []
        if banco:
            banco.salvar_execucao(resumo)
            historico = banco.execucoes()
            alertas = banco.alertas_do_dia(resumo["inicio"][:10])
        # Arquivos estruturados consumidos pela API (local ou AWS) - gerados inclusive em caso de falha
        exportar_arquivos(caminhos.api_json, caminhos.saida, resumo, ordens or [], alertas,
                          sem_inspecao or [], historico)
    except Exception as exc:  # noqa: BLE001
        log.erro("auditoria", f"Não foi possível gravar a execução: {exc}")

    # Publicação no S3 (ingestão do MVP) - falha aqui não derruba o bot, mas é registrada e avisada
    try:
        cfg_pub = json.loads(caminhos.config.read_text(encoding="utf-8")).get("publicacao_s3")
    except (OSError, ValueError):
        cfg_pub = None
    pub = publicar(cfg_pub, caminhos.api_json, log, carimbo=datetime.fromisoformat(resumo["inicio"]),
                   dormir=dormir or time.sleep)
    resumo["publicacao_s3"] = pub["status"]
    if pub["status"] == "FALHA":
        resumo["falhas_envio"] = resumo.get("falhas_envio", 0) + 1
        al.notificar_operacao(f"[Boca de Lobo] Falha ao publicar o resultado no S3: {pub.get('erro')}",
                              log, caminhos.outbox, datetime.fromisoformat(resumo["inicio"]))

    campos = {k: resumo.get(k) for k in ("status", "nivel", "chuva_24h_mm", "linhas_lidas", "inspecoes_validas",
                                         "rejeitados", "duplicados", "ordens_geradas", "excedentes",
                                         "alertas_enviados", "alertas_ignorados", "falhas_envio",
                                         "publicacao_s3")}
    log.info("fim", f"Execução {resumo['id']} finalizada: {resumo['status']} (código {codigo})", campos)
    log.fechar()
    return resumo
