"""Leitura e validação das fontes de dados: cadastro, áreas de risco, inspeções do robô e moradores."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Caminhos


class DadosIndisponiveis(Exception):
    """Fonte obrigatória ausente/ilegível ou nenhuma inspeção válida para processar."""


COLUNAS_INSPECAO = {"id_bueiro", "data_hora_inspecao", "nivel_obstrucao", "tipo_residuo",
                    "confianca_visao", "foto_ref"}
COLUNAS_MORADOR = {"id_morador", "nome", "telefone", "email", "area_id", "canal", "consentimento_lgpd"}


@dataclass
class ResultadoInspecoes:
    validas: dict = field(default_factory=dict)       # id_bueiro -> registro mais recente
    rejeitados: list = field(default_factory=list)    # {arquivo, linha, id_bueiro, motivo}
    arquivos_lidos: int = 0
    arquivos_invalidos: list = field(default_factory=list)
    linhas_lidas: int = 0
    duplicados: int = 0


def _ler_json(arquivo: Path, chave: str) -> list:
    if not arquivo.exists():
        raise DadosIndisponiveis(f"Arquivo obrigatório ausente: {arquivo.name}")
    try:
        conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
        itens = conteudo[chave]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DadosIndisponiveis(f"{arquivo.name} ilegível: {exc}") from exc
    if not isinstance(itens, list) or not itens:
        raise DadosIndisponiveis(f"{arquivo.name} sem registros em '{chave}'")
    return itens


def carregar_areas(caminhos: Caminhos) -> dict:
    return {a["id"]: a for a in _ler_json(caminhos.dados / "areas_risco.json", "areas_risco")}


def carregar_cadastro(caminhos: Caminhos, areas: dict) -> dict:
    cadastro = {}
    for b in _ler_json(caminhos.dados / "bueiros.json", "bueiros"):
        if b.get("area_id") not in areas:
            raise DadosIndisponiveis(f"Bueiro {b.get('id')} aponta para área inexistente {b.get('area_id')}")
        cadastro[b["id"]] = b
    return cadastro


def validar_linha(linha: dict, cadastro: dict, agora: datetime) -> tuple[dict | None, str | None]:
    """Retorna (registro_normalizado, None) ou (None, motivo_da_rejeição)."""
    bid = (linha.get("id_bueiro") or "").strip()
    if not bid:
        return None, "id_bueiro vazio"
    if bid not in cadastro:
        return None, "bueiro não cadastrado (dado inconsistente)"
    bruto = (linha.get("nivel_obstrucao") or "").strip()
    if not bruto:
        return None, "nivel_obstrucao vazio"
    try:
        obstrucao = float(bruto)
    except ValueError:
        return None, f"nivel_obstrucao não numérico: {bruto!r}"
    if not 0 <= obstrucao <= 100:
        return None, f"nivel_obstrucao fora de 0-100: {obstrucao:g}"
    try:
        data = datetime.fromisoformat((linha.get("data_hora_inspecao") or "").strip())
    except ValueError:
        return None, f"data_hora_inspecao inválida: {linha.get('data_hora_inspecao')!r}"
    if data > agora:
        return None, "data_hora_inspecao no futuro (dado inconsistente)"
    try:
        confianca = float(linha.get("confianca_visao") or 1.0)
    except ValueError:
        confianca = 0.0
    return {
        "id_bueiro": bid,
        "data_hora_inspecao": data,
        "nivel_obstrucao": obstrucao,
        "tipo_residuo": (linha.get("tipo_residuo") or "").strip() or "não informado",
        "confianca_visao": confianca,
        "foto_ref": (linha.get("foto_ref") or "").strip(),
    }, None


def carregar_inspecoes(caminhos: Caminhos, cadastro: dict, agora: datetime, log) -> ResultadoInspecoes:
    res = ResultadoInspecoes()
    arquivos = sorted(caminhos.inspecoes.glob("*.csv")) if caminhos.inspecoes.exists() else []
    if not arquivos:
        raise DadosIndisponiveis(f"Nenhum arquivo de inspeção em {caminhos.inspecoes}")
    vistos = set()

    for arq in arquivos:                                        # REPETIÇÃO 1: arquivos
        try:
            with arq.open(encoding="utf-8-sig", newline="") as f:
                leitor = csv.DictReader(f)
                faltando = COLUNAS_INSPECAO - set(leitor.fieldnames or [])
                if faltando:
                    res.arquivos_invalidos.append({"arquivo": arq.name, "motivo": f"colunas ausentes: {sorted(faltando)}"})
                    log.erro("leitura", f"Arquivo {arq.name} ignorado - colunas ausentes {sorted(faltando)}")
                    continue
                res.arquivos_lidos += 1
                for n, linha in enumerate(leitor, start=2):     # REPETIÇÃO 2: registros
                    res.linhas_lidas += 1
                    chave_exata = tuple(sorted((k, (v or "").strip()) for k, v in linha.items() if k))
                    if chave_exata in vistos:
                        res.duplicados += 1
                        res.rejeitados.append({"arquivo": arq.name, "linha": n,
                                               "id_bueiro": linha.get("id_bueiro"), "motivo": "linha duplicada"})
                        continue
                    vistos.add(chave_exata)
                    reg, motivo = validar_linha(linha, cadastro, agora)
                    if motivo:
                        res.rejeitados.append({"arquivo": arq.name, "linha": n,
                                               "id_bueiro": linha.get("id_bueiro"), "motivo": motivo})
                        continue
                    atual = res.validas.get(reg["id_bueiro"])
                    if atual:                                   # mesmo bueiro inspecionado mais de uma vez
                        if atual["arquivo_origem"] == arq.name:  # repetido no mesmo lote = duplicidade
                            res.duplicados += 1
                            res.rejeitados.append({"arquivo": arq.name, "linha": n, "id_bueiro": reg["id_bueiro"],
                                                   "motivo": "bueiro repetido no mesmo lote (mantida a mais recente)"})
                        if reg["data_hora_inspecao"] <= atual["data_hora_inspecao"]:
                            continue                            # mantém a inspeção mais recente
                    reg["arquivo_origem"] = arq.name
                    res.validas[reg["id_bueiro"]] = reg
        except (UnicodeDecodeError, csv.Error, OSError) as exc:
            res.arquivos_invalidos.append({"arquivo": arq.name, "motivo": f"{type(exc).__name__}: {exc}"})
            log.erro("leitura", f"Arquivo {arq.name} ilegível: {exc}")

    log.info("leitura", f"{res.arquivos_lidos} arquivo(s) lido(s), {res.linhas_lidas} linha(s), "
                        f"{len(res.validas)} bueiro(s) com inspeção válida, {len(res.rejeitados)} rejeição(ões), "
                        f"{res.duplicados} duplicidade(s)")
    for r in res.rejeitados:
        log.aviso("validacao", f"Registro rejeitado {r['arquivo']}:{r['linha']} ({r['id_bueiro']}) - {r['motivo']}")
    if not res.validas:
        raise DadosIndisponiveis("Nenhuma inspeção válida encontrada")
    return res


def carregar_moradores(caminhos: Caminhos, log) -> list:
    """Moradores inscritos para alertas. Ausência do arquivo NÃO interrompe o bot (só não há alertas)."""
    arq = caminhos.dados / "moradores_inscritos.csv"
    if not arq.exists():
        log.aviso("leitura", "Cadastro de moradores ausente - alertas a moradores não serão enviados")
        return []
    try:
        with arq.open(encoding="utf-8-sig", newline="") as f:
            leitor = csv.DictReader(f)
            faltando = COLUNAS_MORADOR - set(leitor.fieldnames or [])
            if faltando:
                log.erro("leitura", f"Cadastro de moradores inválido - colunas ausentes {sorted(faltando)}")
                return []
            moradores = [m for m in leitor if (m.get("id_morador") or "").strip()]
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        log.erro("leitura", f"Cadastro de moradores ilegível: {exc}")
        return []
    log.info("leitura", f"{len(moradores)} morador(es) inscrito(s) carregado(s)")
    return moradores
