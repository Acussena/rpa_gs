"""Regras de negócio: nível de risco da chuva, score de prioridade, distribuição para equipes."""
from __future__ import annotations

from datetime import datetime, timedelta

from .previsao import Previsao

NORMAL, ATENCAO, ALERTA = "NORMAL", "ATENCAO", "ALERTA"
ORDEM_PRIORIDADE = {"CRITICA": 0, "ALTA": 1, "MEDIA": 2, "BAIXA": 3}


def classificar_nivel(prev: Previsao, limites: dict) -> tuple[str, str]:
    """DECISÃO principal: a chuva prevista justifica agir?"""
    if prev.chuva_24h_mm >= limites["alerta_mm_24h"]:
        return ALERTA, f"{prev.chuva_24h_mm} mm em 24h >= {limites['alerta_mm_24h']} mm (alerta)"
    if prev.chuva_24h_mm >= limites["atencao_mm_24h"]:
        return ATENCAO, f"{prev.chuva_24h_mm} mm em 24h >= {limites['atencao_mm_24h']} mm (atenção)"
    if (prev.pico_mm_h >= limites["intensidade_forte_mm_h"]
            and prev.probabilidade_max_pct >= limites["probabilidade_minima_pct"]):
        return ATENCAO, (f"pancada forte: pico {prev.pico_mm_h} mm/h com "
                         f"{prev.probabilidade_max_pct:.0f}% de probabilidade")
    return NORMAL, f"{prev.chuva_24h_mm} mm em 24h abaixo do limite de {limites['atencao_mm_24h']} mm"


def calcular_score(obstrucao: float, risco_area: int, historico: int, pesos: dict) -> float:
    """Score 0-100: obstrução da boca de lobo + risco da área + histórico de alagamentos."""
    risco_norm = max(0, min(risco_area, 3)) / 3 * 100
    hist_norm = min(max(historico, 0), 10) * 10
    s = (pesos["peso_obstrucao"] * obstrucao + pesos["peso_risco_area"] * risco_norm
         + pesos["peso_historico"] * hist_norm)
    return round(s, 1)


def classificar_prioridade(score: float, faixas: dict) -> str:
    if score >= faixas["CRITICA"]:
        return "CRITICA"
    if score >= faixas["ALTA"]:
        return "ALTA"
    if score >= faixas["MEDIA"]:
        return "MEDIA"
    return "BAIXA"


def priorizar(validas: dict, cadastro: dict, areas: dict, cfg: dict, nivel: str,
              agora: datetime, log) -> tuple[list, list]:
    """Percorre TODOS os bueiros do cadastro (loop) e devolve (lista_para_limpeza, sem_inspecao)."""
    incluir = set(cfg["prioridades_por_nivel"].get(nivel, []))
    validade = timedelta(days=cfg.get("inspecao_validade_dias", 7))
    conf_min = cfg.get("confianca_visao_minima", 0.6)
    obs_min = cfg.get("obstrucao_minima_para_os", 30)
    lista, sem_inspecao = [], []

    for bid, b in cadastro.items():
        insp = validas.get(bid)
        area = areas[b["area_id"]]
        if insp is None:
            sem_inspecao.append({"id_bueiro": bid, "endereco": b["endereco"], "area": area["nome"]})
            continue
        score = calcular_score(insp["nivel_obstrucao"], area["nivel_risco"],
                               area["alagamentos_ultimos_5_anos"], cfg["score"])
        prioridade = classificar_prioridade(score, cfg["faixas_prioridade"])
        motivos = []
        vencida = agora - insp["data_hora_inspecao"] > validade
        if vencida:
            motivos.append(f"inspeção vencida (> {validade.days} dias)")
        if insp["confianca_visao"] < conf_min:
            motivos.append(f"baixa confiança da visão computacional ({insp['confianca_visao']:.2f})")

        if insp["nivel_obstrucao"] < obs_min:
            decisao = "sem necessidade (obstrução baixa)"
        elif prioridade not in incluir:
            decisao = f"fora do corte para nível {nivel}"
        else:
            decisao = "incluído"
        log.info("priorizacao", f"{bid} obstr={insp['nivel_obstrucao']:g}% área={area['nome']} "
                                f"score={score} -> {prioridade} | {decisao}")
        if decisao != "incluído":
            continue
        lista.append({
            "id_bueiro": bid,
            "endereco": b["endereco"],
            "tipo": b.get("tipo", "boca de lobo"),
            "area_id": area["id"],
            "area": area["nome"],
            "nivel_risco_area": area["nivel_risco"],
            "lat": b["lat"], "lon": b["lon"],
            "nivel_obstrucao": insp["nivel_obstrucao"],
            "tipo_residuo": insp["tipo_residuo"],
            "data_inspecao": insp["data_hora_inspecao"].isoformat(timespec="minutes"),
            "score": score,
            "prioridade": prioridade,
            "reinspecionar": bool(motivos),
            "observacao": "; ".join(motivos),
        })

    lista.sort(key=lambda x: (ORDEM_PRIORIDADE[x["prioridade"]], -x["score"]))
    for i, item in enumerate(lista, 1):
        item["ordem"] = i
    return lista, sem_inspecao


def distribuir_equipes(lista: list, equipes: list) -> tuple[list, list]:
    """Atribui cada bueiro (já ordenado por prioridade) a uma equipe com capacidade,
    preferindo a equipe que já atende a mesma área (menos deslocamento)."""
    restante = {e["id"]: int(e["capacidade"]) for e in equipes}
    areas_da_equipe = {e["id"]: set() for e in equipes}
    atribuidos, excedentes = [], []
    for item in lista:
        livres = [e["id"] for e in equipes if restante[e["id"]] > 0]
        if not livres:
            item["equipe_id"], item["status"] = None, "AGUARDANDO_REFORCO"
            excedentes.append(item)
            continue
        mesma_area = [eid for eid in livres if item["area_id"] in areas_da_equipe[eid]]
        escolhida = mesma_area[0] if mesma_area else max(livres, key=lambda eid: restante[eid])
        restante[escolhida] -= 1
        areas_da_equipe[escolhida].add(item["area_id"])
        item["equipe_id"], item["status"] = escolhida, "ABERTA"
        atribuidos.append(item)
    return atribuidos, excedentes


def areas_para_alerta(lista: list, areas: dict, nivel: str) -> list:
    """ATENCAO: áreas com bueiro CRÍTICO. ALERTA: também todas as áreas de risco >= 2."""
    alvo = {i["area_id"] for i in lista if i["prioridade"] == "CRITICA"}
    if nivel == ALERTA:
        alvo |= {aid for aid, a in areas.items() if a["nivel_risco"] >= 2}
    return sorted(alvo)
