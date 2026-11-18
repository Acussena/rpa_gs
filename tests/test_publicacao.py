"""Testes da publicação automática no S3 - usam um enviador falso, nunca a AWS real."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

from bocadelobo import bot, publicacao  # noqa: E402
from test_bot import AGORA, BaseTemporaria, LogMudo  # noqa: E402

CFG = {"ativo": True, "bucket": "bucket-teste", "prefixo": "rpa", "regiao": "us-east-1", "tentativas": 3}


class EnviadorFalso:
    def __init__(self, falhas=0, etag_errado=False):
        self.falhas, self.etag_errado, self.chamadas, self.objetos = falhas, etag_errado, 0, {}

    def __call__(self, bucket, chave, dados, regiao, arq):
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise ConnectionError("rede indisponível")
        self.objetos[f"{bucket}/{chave}"] = dados
        return "0" * 32 if self.etag_errado else hashlib.md5(dados).hexdigest()


class TestPublicacaoS3(BaseTemporaria):
    def setUp(self):
        super().setUp()
        os.environ["PUBLICAR_S3"] = "0"
        self.rodar(simular_chuva=75)                          # gera output/api/*.json (sem enviar nada)
        self.api = self.caminhos.api_json
        os.environ.pop("PUBLICAR_S3", None)                   # daqui em diante só o enviador falso é usado

    def tearDown(self):
        os.environ["PUBLICAR_S3"] = "0"
        super().tearDown()

    def test_envia_um_arquivo_bocaLobo_data_hora_na_pasta_rpa(self):
        env = EnviadorFalso()
        r = publicacao.publicar(CFG, self.api, LogMudo(), carimbo=AGORA, enviar=env, dormir=lambda s: None)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(list(env.objetos), ["bucket-teste/rpa/bocaLobo_20261116_100000.json"])
        enviado = json.loads(env.objetos["bucket-teste/rpa/bocaLobo_20261116_100000.json"])
        self.assertEqual(enviado["execucao"]["nivel"], "ALERTA")      # resultado
        self.assertTrue(enviado["ordens_servico"])
        self.assertEqual(len(enviado["historico_execucoes"]), 1)      # + histórico no mesmo arquivo

    def test_retentativa_ate_conseguir(self):
        env = EnviadorFalso(falhas=2)
        r = publicacao.publicar(CFG, self.api, LogMudo(), enviar=env, dormir=lambda s: None)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(env.chamadas, 3)                     # 2 falhas + 1 sucesso

    def test_falha_persistente_e_reportada(self):
        log = LogMudo()
        r = publicacao.publicar(CFG, self.api, log, enviar=EnviadorFalso(falhas=99), dormir=lambda s: None)
        self.assertEqual(r["status"], "FALHA")
        self.assertIn("rede indisponível", r["erro"])
        self.assertTrue(any(n == "ERRO" for n, *_ in log.msgs))

    def test_integridade_conferida(self):
        r = publicacao.publicar(CFG, self.api, LogMudo(), enviar=EnviadorFalso(etag_errado=True),
                                dormir=lambda s: None)
        self.assertEqual(r["status"], "FALHA")
        self.assertIn("integridade", r["erro"])

    def test_desligado_por_config_ou_variavel(self):
        env = EnviadorFalso()
        self.assertEqual(publicacao.publicar({**CFG, "ativo": False}, self.api, LogMudo(), enviar=env)["status"],
                         "DESATIVADA")
        os.environ["PUBLICAR_S3"] = "0"
        self.assertEqual(publicacao.publicar(CFG, self.api, LogMudo(), enviar=env)["status"], "DESATIVADA")
        self.assertEqual(env.chamadas, 0)

    def test_bot_nao_cai_se_publicacao_falhar(self):
        antigo = bot.publicar
        bot.publicar = lambda c, p, log, **kw: publicacao.publicar(c, p, log, enviar=EnviadorFalso(falhas=99),
                                                                   dormir=lambda s: None)
        try:
            r = self.rodar(simular_chuva=75, agora=AGORA.replace(hour=13))
        finally:
            bot.publicar = antigo
        self.assertEqual(r["codigo_saida"], 0)
        self.assertEqual(r["publicacao_s3"], "FALHA")
        notif = next(self.caminhos.outbox.glob("operacao_*.log")).read_text(encoding="utf-8")
        self.assertIn("publicar o resultado no S3", notif)


if __name__ == "__main__":
    unittest.main(verbosity=2)
