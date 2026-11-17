"""Gera o fluxo BPMN 2.0 do processo (docs/fluxo_processo.bpmn, abre no bpmn.io / Camunda Modeler)
e a imagem correspondente (docs/fluxo_processo.svg) a partir de um único layout.

    python docs/gerar_bpmn.py
"""
from pathlib import Path
from xml.sax.saxutils import escape

PASTA = Path(__file__).resolve().parent
TAM = {"task": (150, 80), "gw": (50, 50), "start": (36, 36), "end": (36, 36), "error": (36, 36)}

# id, tipo, rótulo, centro x, centro y, extra
NOS = [
    ("inicio", "start", "Todo dia\n06:00", 60, 230, {}),
    ("t_config", "task", "Carregar configuração\ne limites de chuva", 190, 230, {"bpmn": "scriptTask"}),
    ("t_previsao", "task", "Consultar previsão\nOpen-Meteo\n(até 3 tentativas)", 370, 230, {"bpmn": "serviceTask"}),
    ("gw_api", "gw", "API respondeu\ncom dados válidos?", 530, 230, {"lbl": (530, 285, "middle")}),
    ("t_cache", "task", "Ler previsão\nem cache", 530, 90, {"bpmn": "scriptTask"}),
    ("gw_cache", "gw", "Cache com\nmenos de 24h?", 690, 90, {"lbl": (690, 40, "middle")}),
    ("t_falha", "task", "Notificar operação:\nfalha (verificação\nmanual)", 850, 90, {"bpmn": "sendTask"}),
    ("fim_erro", "error", "Falha controlada\n(código 2)", 990, 90, {}),
    ("gw_chuva", "gw", "Chuva prevista\n≥ limite?", 690, 230, {"lbl": (676, 288, "end")}),
    ("t_sem_acao", "task", "Registrar execução\nsem ação", 690, 370, {"bpmn": "scriptTask"}),
    ("fim_sem_acao", "end", "Sem ação", 850, 370, {}),
    ("t_inspecoes", "task", "Ler inspeções do\nrobô + cadastro de\nbueiros e áreas", 850, 230, {"bpmn": "scriptTask"}),
    ("t_validar", "task", "Validar, deduplicar\ne pôr em quarentena\n(loop por registro)", 1030, 230,
     {"bpmn": "scriptTask", "loop": True}),
    ("t_priorizar", "task", "Calcular score e\nclassificar prioridade\n(loop por bueiro)", 1030, 530,
     {"bpmn": "businessRuleTask", "loop": True}),
    ("t_equipes", "task", "Distribuir ordens\nde serviço às equipes\n(capacidade)", 850, 530, {"bpmn": "businessRuleTask"}),
    ("t_mvp", "task", "Publicar no MVP\n(SQLite + JSON/API)", 690, 530, {"bpmn": "serviceTask"}),
    ("gw_alerta", "gw", "Há ordens de serviço\nou áreas em risco?", 530, 530, {"lbl": (530, 482, "middle")}),
    ("t_alertas", "task", "Alertar equipes (OS)\ne moradores das áreas\n(idempotente, LGPD)", 530, 670,
     {"bpmn": "sendTask", "loop": True}),
    ("t_auditoria", "task", "Notificar operação e\nregistrar auditoria", 370, 530, {"bpmn": "sendTask"}),
    ("fim_ok", "end", "Concluído", 230, 530, {}),
]
# origem, destino, lado origem, lado destino, rótulo
FLUXOS = [
    ("inicio", "t_config", "r", "l", ""), ("t_config", "t_previsao", "r", "l", ""),
    ("t_previsao", "gw_api", "r", "l", ""), ("gw_api", "gw_chuva", "r", "l", "Sim"),
    ("gw_api", "t_cache", "t", "b", "Não"), ("t_cache", "gw_cache", "r", "l", ""),
    ("gw_cache", "gw_chuva", "b", "t", "Sim"), ("gw_cache", "t_falha", "r", "l", "Não"),
    ("t_falha", "fim_erro", "r", "l", ""), ("gw_chuva", "t_inspecoes", "r", "l", "Sim"),
    ("gw_chuva", "t_sem_acao", "b", "t", "Não"), ("t_sem_acao", "fim_sem_acao", "r", "l", ""),
    ("t_inspecoes", "t_validar", "r", "l", ""), ("t_validar", "t_priorizar", "b", "t", ""),
    ("t_priorizar", "t_equipes", "l", "r", ""), ("t_equipes", "t_mvp", "l", "r", ""),
    ("t_mvp", "gw_alerta", "l", "r", ""), ("gw_alerta", "t_alertas", "b", "t", "Sim"),
    ("gw_alerta", "t_auditoria", "l", "r", "Não"), ("t_alertas", "t_auditoria", "l", "b", ""),
    ("t_auditoria", "fim_ok", "l", "r", ""),
]
N = {n[0]: n for n in NOS}


def caixa(nid):
    _, tipo, _, cx, cy, _ = N[nid]
    w, h = TAM[tipo]
    return cx - w / 2, cy - h / 2, w, h


def porta(nid, lado):
    x, y, w, h = caixa(nid)
    return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y), "b": (x + w / 2, y + h)}[lado]


def pontos(o, d, lo, ld):
    p1, p2 = porta(o, lo), porta(d, ld)
    if p1[0] == p2[0] or p1[1] == p2[1]:
        return [p1, p2]
    if lo in "lr" and ld in "tb":
        return [p1, (p2[0], p1[1]), p2]
    if lo in "tb" and ld in "lr":
        return [p1, (p1[0], p2[1]), p2]
    mx = (p1[0] + p2[0]) / 2
    return [p1, (mx, p1[1]), (mx, p2[1]), p2]


def gerar_bpmn():
    nome = lambda s: escape(s.replace("\n", " "))
    proc, di = [], []
    for nid, tipo, rot, *_rest in NOS:
        extra = _rest[2]
        ins = "".join(f"<bpmn:incoming>f_{o}_{d}</bpmn:incoming>" for o, d, *_ in FLUXOS if d == nid)
        outs = "".join(f"<bpmn:outgoing>f_{o}_{d}</bpmn:outgoing>" for o, d, *_ in FLUXOS if o == nid)
        if tipo == "start":
            proc.append(f'<bpmn:startEvent id="{nid}" name="{nome(rot)}">{outs}<bpmn:timerEventDefinition '
                        f'id="timer"><bpmn:timeCycle xsi:type="bpmn:tFormalExpression">0 6 * * *</bpmn:timeCycle>'
                        f'</bpmn:timerEventDefinition></bpmn:startEvent>')
        elif tipo == "end":
            proc.append(f'<bpmn:endEvent id="{nid}" name="{nome(rot)}">{ins}</bpmn:endEvent>')
        elif tipo == "error":
            proc.append(f'<bpmn:endEvent id="{nid}" name="{nome(rot)}">{ins}'
                        f'<bpmn:errorEventDefinition id="err_def" errorRef="erro_previsao"/></bpmn:endEvent>')
        elif tipo == "gw":
            proc.append(f'<bpmn:exclusiveGateway id="{nid}" name="{nome(rot)}">{ins}{outs}</bpmn:exclusiveGateway>')
        else:
            tag = extra.get("bpmn", "task")
            loop = '<bpmn:standardLoopCharacteristics/>' if extra.get("loop") else ""
            proc.append(f'<bpmn:{tag} id="{nid}" name="{nome(rot)}">{ins}{outs}{loop}</bpmn:{tag}>')
        x, y, w, h = caixa(nid)
        marcador = ' isMarkerVisible="true"' if tipo == "gw" else ""
        di.append(f'<bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"{marcador}>'
                  f'<dc:Bounds x="{x:g}" y="{y:g}" width="{w}" height="{h}"/></bpmndi:BPMNShape>')
    for o, d, lo, ld, rot in FLUXOS:
        fid = f"f_{o}_{d}"
        proc.append(f'<bpmn:sequenceFlow id="{fid}" name="{rot}" sourceRef="{o}" targetRef="{d}"/>')
        wps = "".join(f'<di:waypoint x="{x:g}" y="{y:g}"/>' for x, y in pontos(o, d, lo, ld))
        di.append(f'<bpmndi:BPMNEdge id="{fid}_di" bpmnElement="{fid}">{wps}</bpmndi:BPMNEdge>')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  id="defs_bocadelobo" targetNamespace="https://citizentech.example/bocadelobo">
  <bpmn:error id="erro_previsao" name="Previsão indisponível" errorCode="2"/>
  <bpmn:process id="processo_boca_de_lobo" name="Bot Boca de Lobo - prevenção de alagamentos" isExecutable="false">
    {chr(10).join("    " + p for p in proc).strip()}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="diagrama">
    <bpmndi:BPMNPlane id="plano" bpmnElement="processo_boca_de_lobo">
    {chr(10).join("      " + d for d in di).strip()}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
'''
    (PASTA / "fluxo_processo.bpmn").write_text(xml, encoding="utf-8")


def texto(cx, cy, rot, tam=12, anchor="middle", cor="#1f2328", peso="normal"):
    linhas = rot.split("\n")
    y0 = cy - (len(linhas) - 1) * (tam + 2) / 2 + tam * 0.35
    return "".join(f'<text x="{cx:g}" y="{y0 + i * (tam + 2):g}" font-size="{tam}" text-anchor="{anchor}" '
                   f'fill="{cor}" font-weight="{peso}">{escape(l)}</text>' for i, l in enumerate(linhas))


def gerar_svg():
    s = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1130 740" width="1130" height="740" '
         'font-family="Segoe UI, Arial, sans-serif">',
         '<defs><marker id="seta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
         'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#444"/></marker></defs>',
         '<rect width="1130" height="740" fill="#ffffff"/>',
         '<text x="20" y="28" font-size="17" font-weight="700" fill="#b0124a">Bot Boca de Lobo — fluxo do processo '
         '(BPMN 2.0)</text>',
         '<text x="20" y="48" font-size="12" fill="#666">Arquivo editável: docs/fluxo_processo.bpmn '
         '(bpmn.io / Camunda Modeler) · ≡ = tarefa em repetição (loop)</text>']
    for o, d, lo, ld, rot in FLUXOS:
        pts = pontos(o, d, lo, ld)
        s.append(f'<polyline points="{" ".join(f"{x:g},{y:g}" for x, y in pts)}" fill="none" stroke="#444" '
                 f'stroke-width="1.6" marker-end="url(#seta)"/>')
        if rot:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            dx = 8 if x2 > x1 else (-8 if x2 < x1 else 6)
            dy = -6 if y2 == y1 else (14 if y2 > y1 else -8)
            anc = "end" if x2 < x1 else "start"
            s.append(f'<text x="{x1 + dx:g}" y="{y1 + dy:g}" font-size="11.5" font-weight="700" '
                     f'fill="{"#1a7f37" if rot == "Sim" else "#cf222e"}" text-anchor="{anc}">{rot}</text>')
    for nid, tipo, rot, cx, cy, extra in NOS:
        x, y, w, h = caixa(nid)
        if tipo == "task":
            s.append(f'<rect x="{x:g}" y="{y:g}" width="{w}" height="{h}" rx="10" fill="#fdeef3" '
                     f'stroke="#b0124a" stroke-width="1.6"/>')
            s.append(texto(cx, cy - (5 if extra.get("loop") else 0), rot, 11.5))
            if extra.get("loop"):
                s.append(texto(cx, y + h - 9, "≡", 13, cor="#b0124a", peso="700"))
        elif tipo == "gw":
            s.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" fill="#fff8e1" '
                     f'stroke="#b07d00" stroke-width="1.6"/>')
            s.append(texto(cx, cy, "✕", 18, cor="#b07d00", peso="700"))
            lx, ly, anc = extra["lbl"]
            s.append(texto(lx, ly, rot, 11, anchor=anc, cor="#5c4400", peso="600"))
        else:
            r = w / 2
            borda = {"start": ("#1a7f37", 1.8), "end": ("#1f2328", 4), "error": ("#cf222e", 4)}[tipo]
            s.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#fff" stroke="{borda[0]}" stroke-width="{borda[1]}"/>')
            if tipo == "start":
                s.append(f'<circle cx="{cx}" cy="{cy}" r="{r - 5}" fill="none" stroke="#1a7f37" stroke-width="1.2"/>'
                         f'<path d="M{cx},{cy - 8} L{cx},{cy} L{cx + 6},{cy + 3}" stroke="#1a7f37" '
                         f'stroke-width="1.6" fill="none"/>')
            if tipo == "error":
                s.append(texto(cx, cy, "⚡", 15, cor="#cf222e"))
            s.append(texto(cx, cy + r + 22, rot, 11, cor="#333"))
    s.append("</svg>")
    (PASTA / "fluxo_processo.svg").write_text("".join(s), encoding="utf-8")


if __name__ == "__main__":
    gerar_bpmn()
    gerar_svg()
    print("Gerados: docs/fluxo_processo.bpmn e docs/fluxo_processo.svg")
