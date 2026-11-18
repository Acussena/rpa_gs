# Versão AWS (preparada, ainda não publicada)

Mesma API e mesmo bot do projeto, empacotados para rodar sem servidor:

```
EventBridge (06:00) ──▶ Lambda "bot" ──┐
                                        ├──▶ S3 (data/, output/, logs/ — mesma estrutura do projeto)
Cliente ──▶ API Gateway ──▶ Lambda "api" ┘
```

| Arquivo | Papel |
|---|---|
| `template.yaml` | Infraestrutura (AWS SAM): bucket S3 criptografado, 2 Lambdas, HTTP API, agendamento diário |
| `empacotar.py` | Gera `aws/dist/lambda/` (para o SAM) e `aws/dist/boca-de-lobo-lambda.zip` (para o console) |
| `../src/aws_lambda.py` | Handlers `handler_api` e `handler_bot`; troca o disco pelo S3 |

Na primeira execução o bot copia os cadastros de exemplo para o bucket. O carrinho pode enviar inspeções
pela API (`POST /api/inspecoes`) ou direto no S3 em `data/inspecoes/`.

## Quando for publicar

```bash
python aws/empacotar.py
sam deploy --guided --template-file aws/template.yaml
```

* **AWS Academy (Learner Lab):** no parâmetro `RoleArn`, use `arn:aws:iam::<ID_DA_CONTA>:role/LabRole`.
* **Conta própria:** crie uma role para Lambda com `AWSLambdaBasicExecutionRole` + leitura/escrita no bucket.
* Defina `ApiToken` para proteger as rotas POST.
* A saída `ApiUrl` é a URL base da API; o dashboard abre na raiz dela.

Os testes de `tests/test_api.py` (classe `TestAwsLambda`) já exercitam essas funções com um S3 simulado.
