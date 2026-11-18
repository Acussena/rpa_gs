"""Testes da API REST (núcleo local) e das funções AWS Lambda (com um S3 falso em memória).

Executar:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "tests"))

import aws_lambda  # noqa: E402
from bocadelobo.api_core import ArmazenamentoLocal, tratar  # noqa: E402
from bocadelobo.bot import executar  # noqa: E402
from test_bot import AGORA, BaseTemporaria  # noqa: E402


class S3Falso:
    """Implementa só o que o código usa: get_object, put_object, list_objects_v2."""

    class exceptions:  # noqa: N801
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.objetos = {}

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objetos:
            raise self.exceptions.NoSuchKey(Key)
        return {"Body": io.BytesIO(self.objetos[Key])}

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803
        self.objetos[Key] = Body

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        return {"Contents": [{"Key": k} for k in sorted(self.objetos) if k.startswith(Prefix)], "IsTruncated": False}


class TestApiLocal(BaseTemporaria):
    def setUp(self):
        super().setUp()
        self.armaz = ArmazenamentoLocal(self.tmp)
        self.bot = lambda **kw: executar(self.tmp, agora=AGORA, console=False, dormir=lambda s: None, **kw)

    def req(self, metodo, rota, params=None, corpo=None, headers=None, token=None):
        if isinstance(corpo, dict):
            corpo = json.dumps(corpo)
        return tratar(metodo, rota, params or {}, corpo, headers or {}, self.armaz,
                      executar_bot=self.bot, token=token, agora=AGORA)

    def test_sem_execucao_retorna_404(self):
        status, corpo = self.req("GET", "/api/status")
        self.assertEqual(status, 404)
        self.assertIn("erro", corpo)

    def test_rotas_de_leitura_apos_execucao(self):
        self.bot(simular_chuva=75)
        st, status = self.req("GET", "/api/status")
        self.assertEqual((st, status["nivel"]), (200, "ALERTA"))
        st, ordens = self.req("GET", "/api/ordens")
        self.assertEqual(len(ordens), status["ordens_geradas"])
        st, criticas = self.req("GET", "/api/ordens", {"prioridade": "critica"})
        self.assertTrue(criticas and all(o["prioridade"] == "CRITICA" for o in criticas))
        st, eq = self.req("GET", "/api/ordens", {"equipe": "EQ-01"})
        self.assertTrue(all(o["equipe_id"] == "EQ-01" for o in eq))
        st, uma = self.req("GET", "/api/ordens/bl-001")
        self.assertEqual((st, uma["id_bueiro"]), (200, "BL-001"))
        self.assertEqual(self.req("GET", "/api/ordens/BL-999")[0], 404)
        st, hist = self.req("GET", "/api/execucoes")
        self.assertEqual(len(hist), 1)
        st, pend = self.req("GET", "/api/pendencias")
        self.assertEqual(len(pend["aguardando_reforco"]), status["excedentes"])
        self.assertEqual(self.req("GET", "/status")[0], 200)            # aceita sem o prefixo /api

    def test_alertas_publicos_sem_dados_pessoais(self):
        self.bot(simular_chuva=75)
        st, pub = self.req("GET", "/api/alertas/publico")
        self.assertEqual(st, 200)
        self.assertTrue(pub)
        texto = json.dumps(pub)
        self.assertNotIn("destinatario_id", texto)
        self.assertNotIn("destino_mascarado", texto)
        st, ar01 = self.req("GET", "/api/alertas/publico", {"area": "AR-01"})
        self.assertEqual([a["area_id"] for a in ar01], ["AR-01"])

    def test_rota_inexistente(self):
        self.assertEqual(self.req("GET", "/api/nada")[0], 404)
        self.assertEqual(self.req("DELETE", "/api/ordens")[0], 404)

    def test_post_inspecoes_grava_csv_e_bot_processa(self):
        corpo = {"robo_id": "carrinho01", "inspecoes": [
            {"id_bueiro": "BL-024", "data_hora_inspecao": "2026-11-16T09:30:00", "nivel_obstrucao": 97,
             "tipo_residuo": "lixo doméstico", "confianca_visao": 0.95, "foto_ref": "img/x.jpg"}]}
        st, resp = self.req("POST", "/api/inspecoes", corpo=corpo)
        self.assertEqual(st, 201)
        self.assertTrue((self.tmp / resp["arquivo"]).exists())
        self.bot(simular_chuva=75)                                         # o bot passa a enxergar o BL-024
        st, ordem = self.req("GET", "/api/ordens/BL-024")
        self.assertEqual(st, 200)
        self.assertEqual(ordem["nivel_obstrucao"], 97)

    def test_post_inspecoes_invalidas(self):
        self.assertEqual(self.req("POST", "/api/inspecoes", corpo="{nao é json")[0], 400)
        self.assertEqual(self.req("POST", "/api/inspecoes", corpo={"inspecoes": []})[0], 400)
        st, resp = self.req("POST", "/api/inspecoes", corpo={"inspecoes": [{"id_bueiro": "BL-001"}]})
        self.assertEqual(st, 422)
        self.assertIn("nivel_obstrucao", resp["detalhes"][0]["erro"])

    def test_token_protege_rotas_de_escrita(self):
        corpo = {"simular_chuva": 5}
        self.assertEqual(self.req("POST", "/api/executar", corpo=corpo, token="segredo")[0], 401)
        self.assertEqual(self.req("POST", "/api/executar", corpo=corpo, token="segredo",
                                  headers={"x-api-key": "errado"})[0], 401)
        st, resumo = self.req("POST", "/api/executar", corpo=corpo, token="segredo",
                              headers={"X-Api-Key": "segredo"})
        self.assertEqual((st, resumo["status"]), (200, "SEM_ACAO"))
        self.assertEqual(self.req("GET", "/api/status", token="segredo")[0], 200)   # leitura é aberta

    def test_executar_valida_parametro(self):
        self.assertEqual(self.req("POST", "/api/executar", corpo={"simular_chuva": "muito"})[0], 400)
        self.assertEqual(self.req("POST", "/api/executar", corpo={"simular_chuva": 9999})[0], 400)

    def test_executar_com_falha_retorna_502(self):
        st, resumo = self.req("POST", "/api/executar", corpo={"falhar_api": True})
        self.assertEqual((st, resumo["status"]), (502, "FALHA_PREVISAO"))
        self.assertEqual(self.req("GET", "/api/status")[1]["status"], "FALHA_PREVISAO")


class TestAwsLambda(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bocadelobo_aws_"))
        self.s3 = S3Falso()
        self.armaz = aws_lambda.ArmazenamentoS3("bucket-teste", s3=self.s3)
        self.tmp_antigo = aws_lambda.TMP
        aws_lambda.TMP = self.tmp / "lambda_tmp"

    def tearDown(self):
        aws_lambda.TMP = self.tmp_antigo
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rodar_bot(self, **kw):
        return aws_lambda.executar_no_s3(self.armaz, agora=AGORA, console=False, dormir=lambda s: None, **kw)

    def evento(self, metodo, rota, corpo=None, query=None, headers=None):
        return {"version": "2.0", "rawPath": rota, "requestContext": {"http": {"method": metodo}},
                "queryStringParameters": query, "headers": headers or {},
                "body": json.dumps(corpo) if corpo is not None else None, "isBase64Encoded": False}

    def test_bot_semeia_bucket_e_publica_resultado(self):
        resumo = self.rodar_bot(simular_chuva=75)
        self.assertEqual(resumo["nivel"], "ALERTA")
        for chave in ("data/bueiros.json", "output/api/ultimo_resultado.json", "output/api/execucoes.json",
                      "output/citizentech.db"):
            self.assertIn(chave, self.s3.objetos)
        self.assertTrue(any(k.startswith("logs/") for k in self.s3.objetos))

    def test_estado_persiste_entre_execucoes_idempotencia(self):
        r1 = self.rodar_bot(simular_chuva=75)
        r2 = aws_lambda.executar_no_s3(self.armaz, agora=AGORA.replace(hour=12), console=False,
                                       dormir=lambda s: None, simular_chuva=75)
        self.assertGreater(r1["alertas_enviados"], 0)
        self.assertEqual(r2["alertas_enviados"], 0)        # banco voltou do S3 -> não reenvia
        hist = json.loads(self.s3.objetos["output/api/execucoes.json"])
        self.assertEqual(len(hist), 2)

    def test_handler_api_gateway(self):
        self.rodar_bot(simular_chuva=75)
        resp = aws_lambda.handler_api(self.evento("GET", "/api/ordens", query={"prioridade": "CRITICA"}),
                                      armaz=self.armaz)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(resp["headers"]["Access-Control-Allow-Origin"], "*")
        self.assertTrue(all(o["prioridade"] == "CRITICA" for o in json.loads(resp["body"])))
        html = aws_lambda.handler_api(self.evento("GET", "/"), armaz=self.armaz)
        self.assertIn("text/html", html["headers"]["Content-Type"])

    def test_handler_api_recebe_inspecao_no_s3(self):
        corpo = {"robo_id": "carrinho01", "inspecoes": [
            {"id_bueiro": "BL-025", "data_hora_inspecao": "2026-11-16T09:00:00", "nivel_obstrucao": 80}]}
        resp = aws_lambda.handler_api(self.evento("POST", "/api/inspecoes", corpo), armaz=self.armaz)
        self.assertEqual(resp["statusCode"], 201)
        chave = json.loads(resp["body"])["arquivo"]
        self.assertIn(chave, self.s3.objetos)
        self.assertIn(b"BL-025", self.s3.objetos[chave])

    def test_handler_api_formato_rest_v1(self):
        resp = aws_lambda.handler_api({"httpMethod": "GET", "path": "/api/status"}, armaz=self.armaz)
        self.assertEqual(resp["statusCode"], 404)           # ainda sem execução


if __name__ == "__main__":
    unittest.main(verbosity=2)
