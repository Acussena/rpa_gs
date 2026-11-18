"""Persistência para integração com o MVP: banco SQLite + JSON/CSV estruturados."""
from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id TEXT PRIMARY KEY, inicio TEXT, fim TEXT, status TEXT, nivel TEXT, justificativa TEXT,
    fonte_previsao TEXT, chuva_24h_mm REAL, pico_mm_h REAL, probabilidade_max_pct REAL,
    linhas_lidas INTEGER, inspecoes_validas INTEGER, rejeitados INTEGER, duplicados INTEGER,
    arquivos_invalidos INTEGER, ordens_geradas INTEGER, excedentes INTEGER,
    alertas_enviados INTEGER, alertas_ignorados INTEGER, falhas_envio INTEGER, mensagem TEXT
);
CREATE TABLE IF NOT EXISTS ordens_servico (
    execucao_id TEXT, ordem INTEGER, id_bueiro TEXT, endereco TEXT, tipo TEXT, area_id TEXT, area TEXT,
    lat REAL, lon REAL, nivel_obstrucao REAL, tipo_residuo TEXT, data_inspecao TEXT, score REAL,
    prioridade TEXT, equipe_id TEXT, status TEXT, reinspecionar INTEGER, observacao TEXT,
    PRIMARY KEY (execucao_id, id_bueiro)
);
CREATE TABLE IF NOT EXISTS alertas (
    chave_idempotencia TEXT PRIMARY KEY, execucao_id TEXT, criado_em TEXT, publico TEXT,
    destinatario_id TEXT, destino_mascarado TEXT, canal TEXT, area_id TEXT, nivel TEXT, mensagem TEXT
);
"""

COLUNAS_OS = ["ordem", "id_bueiro", "endereco", "tipo", "area_id", "area", "lat", "lon", "nivel_obstrucao",
              "tipo_residuo", "data_inspecao", "score", "prioridade", "equipe_id", "status",
              "reinspecionar", "observacao"]


class Banco:
    def __init__(self, arquivo: Path):
        self.arquivo = arquivo
        with closing(self._con()) as con:
            con.executescript(ESQUEMA)

    def _con(self):
        con = sqlite3.connect(self.arquivo)
        con.row_factory = sqlite3.Row
        return con

    def salvar_execucao(self, resumo: dict) -> None:
        cols = ["id", "inicio", "fim", "status", "nivel", "justificativa", "fonte_previsao", "chuva_24h_mm",
                "pico_mm_h", "probabilidade_max_pct", "linhas_lidas", "inspecoes_validas", "rejeitados",
                "duplicados", "arquivos_invalidos", "ordens_geradas", "excedentes", "alertas_enviados",
                "alertas_ignorados", "falhas_envio", "mensagem"]
        with closing(self._con()) as con, con:
            con.execute(f"INSERT OR REPLACE INTO execucoes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [resumo.get(c) for c in cols])

    def salvar_ordens(self, execucao_id: str, ordens: list) -> None:
        with closing(self._con()) as con, con:   # transação: tudo ou nada
            for o in ordens:
                con.execute(
                    f"INSERT OR REPLACE INTO ordens_servico (execucao_id,{','.join(COLUNAS_OS)}) "
                    f"VALUES (?,{','.join('?' * len(COLUNAS_OS))})",
                    [execucao_id] + [int(o[c]) if c == "reinspecionar" else o.get(c) for c in COLUNAS_OS])

    def alerta_ja_enviado(self, chave: str) -> bool:
        with closing(self._con()) as con:
            return con.execute("SELECT 1 FROM alertas WHERE chave_idempotencia=?", (chave,)).fetchone() is not None

    def registrar_alerta(self, a: dict) -> None:
        cols = ["chave_idempotencia", "execucao_id", "criado_em", "publico", "destinatario_id",
                "destino_mascarado", "canal", "area_id", "nivel", "mensagem"]
        with closing(self._con()) as con, con:
            con.execute(f"INSERT INTO alertas ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [a.get(c) for c in cols])

    # ---- consultas usadas pela API do MVP ----
    def ultima_execucao(self) -> dict | None:
        with closing(self._con()) as con:
            r = con.execute("SELECT * FROM execucoes ORDER BY inicio DESC LIMIT 1").fetchone()
            return dict(r) if r else None

    def execucoes(self, limite: int = 30) -> list:
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM execucoes ORDER BY inicio DESC LIMIT ?", (limite,))]

    def ordens(self, execucao_id: str) -> list:
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM ordens_servico WHERE execucao_id=? ORDER BY ordem", (execucao_id,))]

    def alertas(self, execucao_id: str) -> list:
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM alertas WHERE execucao_id=? ORDER BY publico, area_id", (execucao_id,))]

    def alertas_do_dia(self, data: str) -> list:
        """Alertas vigentes no dia (inclui os enviados por execuções anteriores do mesmo dia)."""
        with closing(self._con()) as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM alertas WHERE substr(criado_em,1,10)=? "
                "ORDER BY publico, area_id, criado_em DESC", (data,))]


def exportar_arquivos(pasta_api: Path, pasta_saida: Path, resumo: dict, ordens: list,
                      alertas: list, sem_inspecao: list, historico: list | None = None) -> dict:
    """Gera os arquivos estruturados consumidos pelo MVP (API local/AWS, dashboard, app do cidadão)."""
    pasta_api.mkdir(parents=True, exist_ok=True)
    pacote = {"execucao": resumo, "ordens_servico": ordens, "alertas": alertas,
              "bueiros_sem_inspecao": sem_inspecao}
    arq_json = pasta_api / "ultimo_resultado.json"
    arq_json.write_text(json.dumps(pacote, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (pasta_api / "execucoes.json").write_text(
        json.dumps(historico or [resumo], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    arq_csv = pasta_saida / f"ordens_servico_{resumo['id']}.csv"
    if ordens:
        with arq_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUNAS_OS, extrasaction="ignore", delimiter=";")
            w.writeheader()
            w.writerows(ordens)
    return {"json": str(arq_json), "csv": str(arq_csv) if ordens else None}
