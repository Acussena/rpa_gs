"""Testes automatizados - cenários de SUCESSO, DECISÃO e FALHA.

Executar:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from bocadelobo import regras  # noqa: E402
from bocadelobo.bot import ERRO_DADOS, ERRO_PREVISAO, OK, executar  # noqa: E402
from bocadelobo.config import Caminhos  # noqa: E402
from bocadelobo.dados import validar_linha  # noqa: E402
from bocadelobo.log_utils import higienizar, mascarar_email, mascarar_nome, mascarar_telefone  # noqa: E402
from bocadelobo.previsao import (Previsao, PrevisaoIndisponivel, RespostaInvalida,  # noqa: E402
                                 buscar_previsao, interpretar_resposta)

os.environ["PUBLICAR_S3"] = "0"          # testes nunca enviam nada para a AWS real

AGORA = datetime(2026, 11, 16, 10, 0, 0)   # data de referência fixa -> testes determinísticos
CFG = json.loads((RAIZ / "config" / "config.json").read_text(encoding="utf-8"))


class LogMudo:
    def __init__(self):
        self.msgs = []

    def info(self, e, m, d=None): self.msgs.append(("INFO", e, m))
    def aviso(self, e, m, d=None): self.msgs.append(("WARN", e, m))
    def erro(self, e, m, d=None, exc=False): self.msgs.append(("ERRO", e, m))


def prev(mm, pico=0.0, prob=90.0):
    return Previsao("teste", AGORA.isoformat(), mm, pico, prob, 5)


def resposta_open_meteo(mm_por_hora=3.0, horas=48):
    tempos = [f"2026-11-16T{h:02d}:00" for h in range(24)] + [f"2026-11-17T{h:02d}:00" for h in range(24)]
    return {"hourly": {"time": tempos[:horas], "precipitation": [mm_por_hora] * horas,
                       "precipitation_probability": [80] * horas}}


class RespostaFalsa(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


class BaseTemporaria(unittest.TestCase):
    """Copia config/ e data/ para uma pasta temporária: os testes nunca sujam o repositório."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bocadelobo_"))
        shutil.copytree(RAIZ / "config", self.tmp / "config")
        shutil.copytree(RAIZ / "data", self.tmp / "data")
        self.caminhos = Caminhos(self.tmp)
        self.caminhos.criar_pastas()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rodar(self, **kw):
        kw.setdefault("agora", AGORA)
        kw.setdefault("console", False)
        kw.setdefault("dormir", lambda s: None)
        return executar(self.tmp, **kw)

    def sql(self, q):
        with sqlite3.connect(self.caminhos.banco) as con:
            return con.execute(q).fetchall()


# ----------------------------------------------------------------- DECISÃO (regras)
class TestRegrasDeDecisao(unittest.TestCase):
    L = CFG["limites_chuva"]

    def test_chuva_fraca_nao_aciona(self):
        self.assertEqual(regras.classificar_nivel(prev(5), self.L)[0], regras.NORMAL)

    def test_limite_atencao_inclusivo(self):
        self.assertEqual(regras.classificar_nivel(prev(20), self.L)[0], regras.ATENCAO)

    def test_limite_alerta(self):
        self.assertEqual(regras.classificar_nivel(prev(49.9), self.L)[0], regras.ATENCAO)
        self.assertEqual(regras.classificar_nivel(prev(50), self.L)[0], regras.ALERTA)

    def test_pancada_forte_com_probabilidade_alta_aciona(self):
        self.assertEqual(regras.classificar_nivel(prev(12, pico=11, prob=80), self.L)[0], regras.ATENCAO)

    def test_pancada_forte_com_probabilidade_baixa_nao_aciona(self):
        self.assertEqual(regras.classificar_nivel(prev(12, pico=11, prob=30), self.L)[0], regras.NORMAL)

    def test_score_e_prioridade(self):
        s = regras.calcular_score(92, 3, 9, CFG["score"])          # 46 + 30 + 18
        self.assertAlmostEqual(s, 94.0)
        self.assertEqual(regras.classificar_prioridade(s, CFG["faixas_prioridade"]), "CRITICA")
        self.assertEqual(regras.classificar_prioridade(55, CFG["faixas_prioridade"]), "ALTA")
        self.assertEqual(regras.classificar_prioridade(10, CFG["faixas_prioridade"]), "BAIXA")

    def test_distribuicao_respeita_capacidade(self):
        itens = [{"id_bueiro": f"B{i}", "area_id": "A1", "prioridade": "CRITICA"} for i in range(5)]
        equipes = [{"id": "E1", "capacidade": 2}, {"id": "E2", "capacidade": 2}]
        atrib, exced = regras.distribuir_equipes(itens, equipes)
        self.assertEqual(len(atrib), 4)
        self.assertEqual([e["id_bueiro"] for e in exced], ["B4"])
        self.assertEqual(exced[0]["status"], "AGUARDANDO_REFORCO")


# ----------------------------------------------------------------- VALIDAÇÃO de dados
class TestValidacao(unittest.TestCase):
    CAD = {"BL-001": {}}

    def linha(self, **kw):
        base = {"id_bueiro": "BL-001", "data_hora_inspecao": "2026-11-16T08:00:00", "nivel_obstrucao": "80",
                "tipo_residuo": "folhas", "confianca_visao": "0.9", "foto_ref": "x.jpg"}
        base.update(kw)
        return validar_linha(base, self.CAD, AGORA)

    def test_linha_valida(self):
        reg, motivo = self.linha()
        self.assertIsNone(motivo)
        self.assertEqual(reg["nivel_obstrucao"], 80)

    def test_rejeicoes(self):
        casos = {"fora de 0-100": {"nivel_obstrucao": "150"}, "não numérico": {"nivel_obstrucao": "muito"},
                 "vazio": {"nivel_obstrucao": ""}, "não cadastrado": {"id_bueiro": "BL-999"},
                 "inválida": {"data_hora_inspecao": "16/11/2026"}, "futuro": {"data_hora_inspecao": "2027-01-01T00:00"}}
        for trecho, kw in casos.items():
            with self.subTest(trecho):
                reg, motivo = self.linha(**kw)
                self.assertIsNone(reg)
                self.assertIn(trecho, motivo)


# ----------------------------------------------------------------- PREVISÃO (API)
class TestPrevisao(BaseTemporaria):
    def test_interpreta_somente_proximas_24h(self):
        p = interpretar_resposta(resposta_open_meteo(2.0), AGORA)
        self.assertEqual(p.chuva_24h_mm, 48.0)      # 24 horas x 2 mm
        self.assertEqual(p.pico_mm_h, 2.0)

    def test_resposta_incompleta_e_invalida(self):
        with self.assertRaises(RespostaInvalida):
            interpretar_resposta({"hourly": {"time": []}}, AGORA)
        with self.assertRaises(RespostaInvalida):
            interpretar_resposta(resposta_open_meteo(horas=20), AGORA)   # < 12h futuras

    def test_retentativa_ate_sucesso(self):
        chamadas = []

        def abrir(url, timeout):
            chamadas.append(url)
            if len(chamadas) < 3:
                raise urllib.error.URLError("timeout")
            return RespostaFalsa(json.dumps(resposta_open_meteo(3.0)).encode())

        p = buscar_previsao(CFG, self.caminhos, AGORA, LogMudo(), abrir_url=abrir, dormir=lambda s: None)
        self.assertEqual(len(chamadas), 3)
        self.assertEqual(p.fonte, "open-meteo")
        self.assertTrue((self.caminhos.cache / "previsao_cache.json").exists())

    def test_api_fora_usa_cache_valido(self):
        abrir_ok = lambda url, timeout: RespostaFalsa(json.dumps(resposta_open_meteo(3.0)).encode())
        buscar_previsao(CFG, self.caminhos, AGORA, LogMudo(), abrir_url=abrir_ok)
        p = buscar_previsao(CFG, self.caminhos, AGORA, LogMudo(), forcar_falha=True, dormir=lambda s: None)
        self.assertTrue(p.fonte.startswith("cache"))
        self.assertEqual(p.chuva_24h_mm, 72.0)

    def test_api_fora_sem_cache_levanta_excecao(self):
        with self.assertRaises(PrevisaoIndisponivel):
            buscar_previsao(CFG, self.caminhos, AGORA, LogMudo(), forcar_falha=True, dormir=lambda s: None)

    def test_cache_expirado_e_descartado(self):
        antigo = Previsao("open-meteo", "2026-11-14T06:00:00", 80, 20, 90, 10)
        (self.caminhos.cache / "previsao_cache.json").write_text(json.dumps(antigo.to_dict()))
        with self.assertRaises(PrevisaoIndisponivel):
            buscar_previsao(CFG, self.caminhos, AGORA, LogMudo(), forcar_falha=True, dormir=lambda s: None)

    def test_json_corrompido_conta_como_falha(self):
        abrir = lambda url, timeout: RespostaFalsa(b"<html>erro 502</html>")
        with self.assertRaises(PrevisaoIndisponivel):
            buscar_previsao(CFG, self.caminhos, AGORA, LogMudo(), abrir_url=abrir, dormir=lambda s: None)


# ----------------------------------------------------------------- PONTA A PONTA
class TestPontaAPonta(BaseTemporaria):
    def test_sucesso_chuva_forte_gera_os_alertas_e_integra_mvp(self):
        r = self.rodar(simular_chuva=75)
        self.assertEqual(r["codigo_saida"], OK)
        self.assertEqual(r["nivel"], "ALERTA")
        self.assertGreater(r["ordens_geradas"], 0)
        self.assertGreater(r["alertas_enviados"], 0)
        # integração: banco consumido pela API do MVP
        ordens = self.sql("SELECT id_bueiro, prioridade, ordem FROM ordens_servico ORDER BY ordem")
        self.assertEqual(len(ordens), r["ordens_geradas"])
        self.assertEqual(ordens[0][1], "CRITICA")                 # mais urgente primeiro
        # integração: arquivo estruturado
        pacote = json.loads((self.caminhos.api_json / "ultimo_resultado.json").read_text(encoding="utf-8"))
        self.assertEqual(pacote["execucao"]["id"], r["id"])
        self.assertEqual(len(pacote["ordens_servico"]), r["ordens_geradas"])

    def test_decisao_atencao_inclui_menos_bueiros_que_alerta(self):
        atencao = self.rodar(simular_chuva=30)
        alerta = self.rodar(simular_chuva=80, agora=AGORA.replace(hour=11))
        self.assertEqual(atencao["nivel"], "ATENCAO")
        self.assertLess(atencao["ordens_geradas"], alerta["ordens_geradas"])
        medias = self.sql(f"SELECT COUNT(*) FROM ordens_servico WHERE execucao_id='{atencao['id']}' "
                          f"AND prioridade='MEDIA'")[0][0]
        self.assertEqual(medias, 0)

    def test_decisao_chuva_fraca_nao_gera_acao(self):
        r = self.rodar(simular_chuva=5)
        self.assertEqual(r["status"], "SEM_ACAO")
        self.assertEqual(r["ordens_geradas"], 0)
        self.assertEqual(r["alertas_enviados"], 0)

    def test_dados_invalidos_vao_para_quarentena(self):
        r = self.rodar(simular_chuva=75)
        self.assertGreaterEqual(r["rejeitados"], 6)
        self.assertGreaterEqual(r["duplicados"], 1)
        self.assertEqual(r["arquivos_invalidos"], 1)
        arq = next(self.caminhos.quarentena.glob("rejeitados_*.csv"))
        conteudo = arq.read_text(encoding="utf-8-sig")
        self.assertIn("BL-999", conteudo)
        self.assertIn("colunas ausentes", conteudo)

    def test_idempotencia_nao_reenvia_alertas_no_mesmo_dia(self):
        r1 = self.rodar(simular_chuva=75)
        r2 = self.rodar(simular_chuva=75, agora=AGORA.replace(hour=12))
        self.assertGreater(r1["alertas_enviados"], 0)
        self.assertEqual(r2["alertas_enviados"], 0)
        self.assertEqual(r2["alertas_ignorados"], r1["alertas_enviados"])

    def test_lgpd_morador_sem_consentimento_nao_recebe(self):
        self.rodar(simular_chuva=75)
        ids = {x[0] for x in self.sql("SELECT destinatario_id FROM alertas WHERE publico='morador'")}
        self.assertNotIn("M-004", ids)     # consentimento_lgpd = nao
        self.assertNotIn("M-013", ids)

    def test_falha_api_sem_cache_encerra_com_codigo_2(self):
        r = self.rodar(falhar_api=True)
        self.assertEqual(r["codigo_saida"], ERRO_PREVISAO)
        self.assertEqual(r["status"], "FALHA_PREVISAO")
        self.assertEqual(self.sql("SELECT status FROM execucoes")[0][0], "FALHA_PREVISAO")
        notif = next(self.caminhos.outbox.glob("operacao_*.log")).read_text(encoding="utf-8")
        self.assertIn("FALHA", notif)

    def test_sem_arquivos_de_inspecao_encerra_com_codigo_3(self):
        shutil.rmtree(self.caminhos.inspecoes)
        r = self.rodar(simular_chuva=75)
        self.assertEqual(r["codigo_saida"], ERRO_DADOS)
        self.assertEqual(r["status"], "FALHA_DADOS")

    def test_logs_nao_expoem_dados_pessoais(self):
        self.rodar(simular_chuva=75)
        texto_logs = "".join(p.read_text(encoding="utf-8") for p in self.caminhos.logs.glob("*.jsonl"))
        texto_saidas = (self.caminhos.api_json / "ultimo_resultado.json").read_text(encoding="utf-8")
        moradores = (self.caminhos.dados / "moradores_inscritos.csv").read_text(encoding="utf-8").splitlines()[1:]
        for linha in moradores:
            _, nome, tel, email, *_ = linha.split(",")
            for dado in (nome, tel, email):
                self.assertNotIn(dado, texto_logs)
                self.assertNotIn(dado, texto_saidas)
        for linha in texto_logs.splitlines():
            json.loads(linha)                                    # todo log é JSON válido


class TestMascaramento(unittest.TestCase):
    def test_mascaras(self):
        self.assertEqual(mascarar_telefone("(11) 92528-4872"), "(11) 9****-**72")
        self.assertEqual(mascarar_email("ana1@exemplo.com"), "a***@exemplo.com")
        self.assertEqual(mascarar_nome("Ana Souza"), "A. S.")
        self.assertNotIn("4872", higienizar("ligar para (11) 92528-4872"))
        self.assertIn("EX20261116T060512", higienizar("execução EX20261116T060512"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
