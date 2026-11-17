# 🌧️ CitizenTech · Boca de Lobo — Bot RPA de prevenção de alagamentos

> **FIAP · Global Solution 2026.2 · Engenharia de Software 4º ano**
> Disciplina: **Robotic Process Automation** — *Do Processo Manual à Automação Inteligente*
> Componente do MVP: **Automação**

Todo verão, moradores das áreas baixas e periféricas veem a rua virar rio porque as **bocas de lobo estavam
entupidas de lixo e folhas** quando a chuva chegou. Hoje, decidir *quais* bueiros limpar antes de um temporal é um
processo manual: alguém consulta a previsão, abre planilhas de inspeção, cruza com o mapa de áreas de risco, monta a
lista para as equipes e avisa a população por telefone/WhatsApp. É lento, sujeito a erro e acontece tarde demais.

**O bot Boca de Lobo automatiza esse processo de ponta a ponta.** Toda manhã ele:

1. **Lê a previsão de chuva** das próximas 24h (API pública Open-Meteo), com retentativa e cache de contingência;
2. **Decide** se a chuva prevista passa do limite (NORMAL / ATENÇÃO / ALERTA);
3. Se passar, **lê as inspeções** feitas pelo robô de visão computacional nas bocas de lobo, **valida, deduplica e
   põe em quarentena** dados ruins;
4. **Calcula um score de prioridade** para cada bueiro (obstrução + risco da área + histórico de alagamentos);
5. **Gera ordens de serviço** distribuídas entre as equipes de limpeza respeitando a capacidade de cada uma;
6. **Publica o resultado no MVP** (banco SQLite + JSON/CSV + API REST + dashboard com mapa);
7. **Dispara alertas** às equipes e aos moradores inscritos das áreas em risco (*onde não passar*), sem duplicar e
   respeitando o consentimento LGPD;
8. **Registra logs de auditoria** (JSON Lines) e notifica a operação — inclusive quando algo falha.

![Dashboard do MVP](assets/dashboard_mvp.png)

---

## 👥 Integrantes

| Nome | RM |
|---|---|
| *preencher* | *RM* |
| *preencher* | *RM* |
| *preencher* | *RM* |

🎥 **Vídeo demonstrativo:** *link do vídeo* · 📄 **Relatório técnico:** [`docs/Relatorio_Tecnico_RPA.pdf`](docs/Relatorio_Tecnico_RPA.pdf)

---

## 🧭 Fluxo do processo (BPMN)

![Fluxo BPMN](docs/fluxo_processo.svg)

Arquivo BPMN 2.0 editável: [`docs/fluxo_processo.bpmn`](docs/fluxo_processo.bpmn) (abra em <https://demo.bpmn.io>
ou no Camunda Modeler). Gerado por [`docs/gerar_bpmn.py`](docs/gerar_bpmn.py).

## 🏗️ Arquitetura

```
 Agendador (06:00)        ┌──────────────────── Bot RPA (Python) ────────────────────┐
 Windows / cron / GitHub  │ previsao.py → regras.py → dados.py → regras.py → alertas │
 Actions ───────────────▶ │  (API+cache)  (decisão)   (validação)  (score/OS)        │
                          └───────┬───────────────────────────────┬─────────────────┘
  Fontes:                         │ persistencia.py               │ log_utils.py
  • Open-Meteo (API)              ▼                               ▼
  • data/inspecoes/*.csv   output/citizentech.db  ◀── src/api.py ── mvp/index.html
    (robô de inspeção)     output/api/*.json          (API REST)    (dashboard/mapa)
  • data/bueiros.json      output/outbox/*.jsonl  → gateway SMS/WhatsApp/e-mail
  • data/areas_risco.json  logs/bot_AAAAMMDD.jsonl (auditoria)
  • data/moradores_inscritos.csv
```

| Módulo | Responsabilidade |
|---|---|
| `src/main.py` | Ponto de entrada (CLI) chamado pelo agendador; devolve código de saída |
| `src/bocadelobo/bot.py` | Orquestra todas as etapas e trata exceções |
| `src/bocadelobo/previsao.py` | Consulta a Open-Meteo, 3 tentativas com backoff, valida resposta, cache |
| `src/bocadelobo/dados.py` | Lê cadastros e inspeções, valida linha a linha, deduplica |
| `src/bocadelobo/regras.py` | Regras de negócio: nível de chuva, score, prioridade, equipes, áreas de alerta |
| `src/bocadelobo/alertas.py` | Mensagens, idempotência, LGPD, webhook da operação |
| `src/bocadelobo/persistencia.py` | SQLite + exportação JSON/CSV para o MVP |
| `src/bocadelobo/log_utils.py` | Logs JSON de auditoria com mascaramento de dados pessoais |
| `src/api.py` | API REST do MVP + serve o dashboard |

**Tecnologias:** Python 3.9+ **somente biblioteca padrão** (sem `pip install`), SQLite, API Open-Meteo, Leaflet +
OpenStreetMap no dashboard, GitHub Actions para agendamento. *Por quê Python e não UiPath/Power Automate?* O processo
é 100% de dados (API, arquivos, banco, mensagens) — não há interface gráfica legada para "clicar"; em Python o bot
fica versionado, testável automaticamente, roda de graça em qualquer servidor/agendador e se integra direto ao MVP.

## ⚙️ Regras de negócio

**Decisão 1 — a chuva justifica agir?** (`config/config.json → limites_chuva`)

| Condição | Nível | Ação |
|---|---|---|
| chuva 24h ≥ 50 mm | **ALERTA** | OS para prioridades CRÍTICA, ALTA e MÉDIA; alerta a todas as áreas de risco ≥ 2 |
| chuva 24h ≥ 20 mm **ou** pico ≥ 10 mm/h com probabilidade ≥ 60% | **ATENÇÃO** | OS para CRÍTICA e ALTA; alerta às áreas com bueiro CRÍTICO |
| abaixo disso | NORMAL | registra execução e encerra (sem ação) |

**Score de prioridade (0–100)** = 0,5 × obstrução(%) + 0,3 × risco da área (1–3 → 0–100) + 0,2 × histórico de
alagamentos (0–10 → 0–100) → **CRÍTICA ≥ 70 · ALTA ≥ 50 · MÉDIA ≥ 30 · BAIXA**.

**Outras decisões:** obstrução < 30% não gera OS · inspeção com mais de 7 dias ou confiança da visão < 0,6 → OS
marcada para **reinspeção** · bueiro sem inspeção → pedido de nova ronda do robô · equipes com capacidade
(3 × 5 bueiros); acima disso → **AGUARDANDO_REFORCO** e aviso à operação · equipe preferida = a que já atende a mesma
área (menos deslocamento).

**Repetição:** loop pelos arquivos de inspeção → loop pelas linhas → loop por bueiro do cadastro (score) → loop por
OS (equipes) → loop por área e por morador (alertas).

## 🛡️ Exceções e resiliência

| Falha prevista | Tratamento |
|---|---|
| API de previsão fora do ar / timeout / HTTP ≠ 200 | 3 tentativas com backoff exponencial (1s, 2s) |
| API responde lixo (HTML, JSON incompleto, < 12h de dados, valor negativo) | tratado como falha → retentativa |
| API indisponível após tentativas | usa **cache** da última previsão se tiver < 24h |
| Sem API e sem cache válido | **falha controlada**: status `FALHA_PREVISAO`, código de saída 2, notifica a operação |
| Arquivo de inspeção com colunas erradas / ilegível | arquivo ignorado, registrado em `output/quarentena/` |
| Linha inválida (obstrução vazia, > 100, não numérica, data inválida/futura, bueiro não cadastrado) | linha rejeitada com motivo, demais seguem |
| Linha duplicada / bueiro repetido no lote | descartada; mantém a inspeção mais recente |
| Nenhuma inspeção válida / cadastro ausente | `FALHA_DADOS`, código 3, notifica a operação |
| Reexecução no mesmo dia | **idempotência**: alerta com mesma chave não é reenviado |
| Webhook da operação fora do ar | 3 tentativas; falha contabilizada no resumo, sem derrubar o bot |
| Erro inesperado | capturado, logado, `FALHA` código 1 — **nunca falha silenciosa** |

## 📜 Logs e auditoria

* `logs/bot_AAAAMMDD.jsonl` — um evento por linha: data/hora, nível, `execucao_id`, etapa, mensagem e dados.
* Tabela `execucoes` no banco — resumo de cada execução (lidos, válidos, rejeitados, duplicados, OS, alertas, falhas).
* `output/quarentena/rejeitados_<execucao>.csv` — cada registro rejeitado e o motivo.
* Dados pessoais **nunca** vão para log: telefone e e-mail são mascarados (`(11) 9****-**72`, `a***@exemplo.com`) e
  um filtro remove qualquer telefone/e-mail que escape. Alertas referenciam o morador pelo **ID**.

## 🔌 Integração com o MVP CitizenTech

O resultado é consumido pelos outros componentes por **três vias**:

| Via | Onde | Quem consome |
|---|---|---|
| Banco de dados | `output/citizentech.db` (tabelas `execucoes`, `ordens_servico`, `alertas`) | back-end do MVP |
| API REST | `python src/api.py` → `GET /api/status`, `/api/ordens`, `/api/alertas`, `/api/alertas/publico`, `/api/execucoes` | dashboard, app do cidadão |
| Arquivos estruturados | `output/api/ultimo_resultado.json`, `output/ordens_servico_<execucao>.csv` | app das equipes, BI |

O **dashboard** (`mvp/index.html`, servido em `/`) consome a API e mostra nível de risco, KPIs, mapa com as bocas de
lobo por prioridade, lista para limpeza, alertas emitidos e histórico de execuções.

## ▶️ Como executar

Requisito: **Python 3.9+** (nenhuma dependência externa).

```bash
python src/main.py                      # previsão real (Open-Meteo)
python src/main.py --simular-chuva 75   # cenário de chuva forte (ALERTA)
python src/main.py --simular-chuva 30   # cenário ATENÇÃO
python src/main.py --simular-chuva 5    # cenário sem ação
python src/main.py --falhar-api         # simula API fora do ar (cache ou falha controlada)
python src/api.py                       # API + dashboard em http://localhost:8000
python -m unittest discover -s tests -v # testes automatizados
```

No Windows, use `py` no lugar de `python` se necessário. Webhook opcional para a operação (Discord/Slack/Teams):
defina a variável `ALERTA_WEBHOOK_URL`.

**Agendamento diário:** GitHub Actions ([`.github/workflows/bot-diario.yml`](.github/workflows/bot-diario.yml), 06:00)
ou Agendador do Windows ([`scripts/agendar_windows.ps1`](scripts/agendar_windows.ps1)) ou cron
(`0 6 * * * cd /caminho && python src/main.py`).

## ✅ Testes

26 testes automatizados (`tests/test_bot.py`) cobrindo **sucesso, decisão e falha**; evidências em
[`tests/evidencias/`](tests/evidencias/):

| Evidência | Cenário | Resultado |
|---|---|---|
| `00_testes_automatizados.txt` | suíte completa | 26/26 OK |
| `01_previsao_real.txt` | API real | previsão obtida, decisão tomada |
| `02_api_fora_usa_cache.txt` | falha — API fora | 3 tentativas → usa cache |
| `03_falha_api_sem_cache.txt` | falha — API fora sem cache | `FALHA_PREVISAO`, código 2, operação notificada |
| `04_decisao_sem_acao.txt` | decisão — 5 mm | `SEM_ACAO` |
| `05_decisao_atencao.txt` | decisão — 30 mm | ATENÇÃO: só CRÍTICA/ALTA |
| `06_sucesso_alerta.txt` | sucesso — 75 mm | ALERTA: 19 OS, 17 alertas, 7 rejeições em quarentena |
| `07_idempotencia_reexecucao.txt` | reexecução | 0 alertas reenviados |

## 🔒 Segurança e LGPD

* **Minimização:** o bot só lê do morador o necessário para o alerta (área, canal, contato); logs e saídas usam o ID.
* **Consentimento:** só recebe alerta quem tem `consentimento_lgpd = sim` (base legal: consentimento, art. 7º, I;
  e proteção da vida/incolumidade física, art. 7º, VII).
* **Mascaramento** de telefone/e-mail em tudo que é exibido; filtro de segurança nos logs.
* **Segredos** (URL do webhook) só por variável de ambiente / GitHub Secrets — nunca no código.
* **Dados de exemplo fictícios** (nomes, telefones e endereços inventados).
* API do MVP somente leitura; a rota pública `/api/alertas/publico` não contém dados pessoais.

## 📁 Estrutura

```
├── README.md
├── config/config.json          # limites, pesos, equipes (sem mexer em código)
├── data/                       # fontes: cadastro, áreas de risco, moradores, inspeções do robô
├── src/                        # código-fonte Python (bot + API)
├── mvp/index.html              # dashboard do MVP
├── docs/                       # BPMN, relatório técnico PDF e geradores
├── assets/                     # prints e evidências visuais
├── logs/                       # amostra de logs gerados (sem dados sensíveis)
├── output/                     # saídas da última demonstração (banco, JSON, CSV, outbox, quarentena)
├── tests/                      # testes automatizados + evidências
├── scripts/agendar_windows.ps1
└── .github/workflows/bot-diario.yml
```
