"""Gera o Relatório Técnico em PDF (docs/Relatorio_Tecnico_RPA.pdf).

1. Preencha docs/equipe.json (nomes, RMs, links)
2. python docs/gerar_relatorio.py
Usa o Microsoft Edge ou Google Chrome em modo headless para imprimir o HTML em PDF.
"""
import base64
import html
import json
import shutil
import subprocess
from pathlib import Path

DOCS = Path(__file__).resolve().parent
RAIZ = DOCS.parent
eq = json.loads((DOCS / "equipe.json").read_text(encoding="utf-8"))


def img(caminho, estilo="width:100%"):
    dados = base64.b64encode((RAIZ / caminho).read_bytes()).decode()
    return f'<img src="data:image/png;base64,{dados}" style="{estilo}">'


def trecho(arquivo, filtro, n):
    linhas = [l for l in (RAIZ / arquivo).read_text(encoding="utf-8").splitlines() if any(f in l for f in filtro)]
    return html.escape("\n".join(linhas[:n]))


svg_fluxo = (DOCS / "fluxo_processo.svg").read_text(encoding="utf-8").replace(
    'width="1130" height="740"', 'width="100%"')
log_json = html.escape("\n".join((RAIZ / "logs").glob("*.jsonl").__next__().read_text(encoding="utf-8")
                                 .splitlines()[-3:]))
integrantes = "".join(f"<tr><td>{html.escape(i['nome'])}</td><td>{html.escape(i['rm'])}</td></tr>"
                      for i in eq["integrantes"])

HTML = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Relatório Técnico - Boca de Lobo</title>
<style>
@page {{ size:A4; margin:16mm 15mm 16mm 15mm; }}
body {{ font: 10.5pt/1.5 "Segoe UI", Arial, sans-serif; color:#1f2328; }}
h1 {{ font-size:22pt; margin:0 0 6px; color:#b0124a; }}
h2 {{ font-size:14pt; color:#b0124a; border-bottom:2px solid #f3c1d2; padding-bottom:3px; margin:22px 0 8px; break-after:avoid; }}
h3 {{ font-size:11pt; margin:14px 0 4px; }}
table {{ width:100%; border-collapse:collapse; margin:6px 0 10px; font-size:9.5pt; break-inside:avoid; }}
th, td {{ border:1px solid #d8dee4; padding:4px 7px; text-align:left; vertical-align:top; }}
th {{ background:#fdeef3; }}
pre {{ background:#0f1115; color:#d6e2ee; padding:9px 11px; border-radius:6px; font-size:7.6pt; white-space:pre-wrap;
       word-break:break-all; break-inside:avoid; }}
code {{ background:#f1f3f5; padding:0 4px; border-radius:3px; font-size:9pt; }}
.capa {{ height:250mm; display:flex; flex-direction:column; justify-content:center; break-after:page; }}
.capa .tag {{ letter-spacing:.25em; color:#b0124a; font-weight:700; font-size:10pt; }}
.capa h1 {{ font-size:32pt; line-height:1.15; margin:14px 0; }}
.capa .sub {{ font-size:14pt; color:#57606a; }}
.box {{ background:#fdeef3; border-left:4px solid #b0124a; padding:8px 12px; border-radius:4px; margin:8px 0; break-inside:avoid; }}
.quebra {{ break-before:page; }}
figure {{ margin:8px 0; break-inside:avoid; }} figcaption {{ font-size:8.5pt; color:#57606a; text-align:center; }}
.dois {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
</style></head><body>

<section class="capa">
  <div class="tag">FIAP · GLOBAL SOLUTION 2026.2 · CITIZENTECH</div>
  <h1>Boca de Lobo<br>Bot RPA de prevenção de alagamentos</h1>
  <div class="sub">Relatório Técnico — Robotic Process Automation<br>“Do Processo Manual à Automação Inteligente”</div>
  <p style="margin-top:28px">Professores: Bruno Diniz e Cibele Ribeiro · {html.escape(eq['turma'])}</p>
  <table style="width:70%"><tr><th>Integrante</th><th>RM</th></tr>{integrantes}</table>
  <p><b>Repositório:</b> {html.escape(eq['link_github'])}<br><b>Vídeo:</b> {html.escape(eq['link_video'])}</p>
</section>

<h2>1. Identificação da CitizenTech e problema resolvido</h2>
<p><b>CitizenTech:</b> <i>Boca de Lobo</i> — área de <b>segurança e emergências (enchentes)</b>. Cidadão-alvo: morador de
região que alaga todo verão, principalmente áreas baixas e periféricas (no MVP: várzea do Rio Tietê, Zona Leste de São Paulo —
Jardim Pantanal, Vila Itaim, Jardim Romano, Jardim Helena e São Miguel).</p>
<p><b>Problema:</b> boa parte dos alagamentos urbanos é agravada por bocas de lobo e sarjetas entupidas de lixo e folhas.
A solução CitizenTech usa um robô que inspeciona os bueiros e registra o nível de obstrução — mas, sem automação, transformar
esses dados em ação continua manual: alguém precisa olhar a previsão, abrir as planilhas de inspeção, cruzar com as áreas de
risco, montar a lista para as equipes e avisar os moradores. Isso consome horas, depende de uma pessoa disponível de madrugada
e costuma acontecer <b>depois</b> que a chuva começa.</p>
<div class="box"><b>Papel da automação no MVP:</b> é o componente que executa esse processo operacional sozinho, todos os dias,
de forma confiável e integrada: coleta (previsão + inspeções), consulta (cadastro e áreas de risco), valida, processa
(prioriza e distribui) e disponibiliza os dados (banco, API, arquivos e alertas) para o restante da solução.</div>

<h2>2. Objetivo da automação e benefício para o cidadão</h2>
<p><b>Objetivo:</b> toda manhã, sem intervenção humana, decidir se a chuva prevista exige ação e, em caso positivo, entregar
às equipes de limpeza uma <b>lista priorizada de bocas de lobo</b> para desentupir antes do temporal e avisar os
<b>moradores das áreas em risco</b> sobre onde não passar.</p>
<table><tr><th>Para quem</th><th>Benefício</th></tr>
<tr><td>Morador da área de risco</td><td>Menos alagamento na sua rua (bueiro limpo a tempo) e aviso antecipado das vias a evitar, com telefones de emergência.</td></tr>
<tr><td>Equipe de limpeza</td><td>Ordem de serviço pronta às 06:00, com os bueiros mais críticos primeiro e agrupados por área (menos deslocamento).</td></tr>
<tr><td>Defesa Civil / Subprefeitura</td><td>Decisão padronizada e auditável; aviso automático quando a capacidade das equipes não basta ou quando o bot falha.</td></tr>
</table>

<h2>3. Descrição do processo e desenho do fluxo</h2>
<div class="dois">
<div><h3>Antes (manual — AS-IS)</h3><ol>
<li>Técnico abre site de meteorologia e interpreta a previsão.</li>
<li>Abre planilhas das rondas de inspeção, uma a uma.</li>
<li>Procura cada bueiro no mapa de áreas de risco.</li>
<li>Escolhe “de cabeça” quais limpar e liga para as equipes.</li>
<li>Avisa moradores por grupos de WhatsApp (quando avisa).</li></ol>
<p>⏱ ~2–3 h por dia de chuva · sem registro · sujeito a erro e esquecimento.</p></div>
<div><h3>Depois (automatizado — TO-BE)</h3><ol>
<li>Agendador dispara o bot às 06:00.</li>
<li>Bot consulta a API de previsão (retentativa + cache).</li>
<li>Decide o nível (NORMAL / ATENÇÃO / ALERTA).</li>
<li>Lê, valida e deduplica as inspeções do robô.</li>
<li>Calcula score, gera e distribui as ordens de serviço.</li>
<li>Publica no MVP, alerta equipes e moradores, registra auditoria.</li></ol>
<p>⏱ segundos · 100% registrado · mesma regra todos os dias.</p></div>
</div>
<p><b>Entradas:</b> previsão horária Open-Meteo (API), <code>data/inspecoes/*.csv</code> (robô de inspeção),
<code>bueiros.json</code>, <code>areas_risco.json</code>, <code>moradores_inscritos.csv</code>, <code>config.json</code>.
<b>Saídas:</b> ordens de serviço, alertas, banco SQLite, JSON/CSV, API REST, logs e relatório de quarentena.</p>
<figure>{svg_fluxo}<figcaption>Figura 1 — Fluxo do processo em BPMN 2.0 (arquivo editável <code>docs/fluxo_processo.bpmn</code>).</figcaption></figure>

<h2 class="quebra">4. Tecnologias utilizadas e justificativa</h2>
<table><tr><th>Tecnologia</th><th>Uso</th><th>Justificativa</th></tr>
<tr><td>Python 3.9+ (só biblioteca padrão)</td><td>Bot, regras, API</td><td>Processo 100% de dados (API, arquivos, banco, mensagens) — não há tela legada para automatizar com cliques. Versionável no Git, testável automaticamente, roda em qualquer servidor sem licença e sem <code>pip install</code>.</td></tr>
<tr><td>API Open-Meteo</td><td>Previsão horária de chuva</td><td>Pública, gratuita, sem chave, com precipitação e probabilidade por hora.</td></tr>
<tr><td>SQLite</td><td>Banco do MVP</td><td>Transacional, zero configuração; troca simples por PostgreSQL em produção.</td></tr>
<tr><td>JSON Lines</td><td>Logs de auditoria</td><td>Um evento por linha, legível por pessoas e por ferramentas (ELK, Grafana Loki).</td></tr>
<tr><td>http.server + Leaflet/OpenStreetMap</td><td>API REST e dashboard</td><td>Entrega o resultado ao MVP e permite visualizar o mapa de prioridade.</td></tr>
<tr><td>GitHub Actions / Agendador do Windows / cron</td><td>Execução diária 06:00</td><td>Qualquer agendador funciona, pois o bot devolve código de saída (0, 1, 2, 3).</td></tr>
<tr><td>BPMN 2.0 (bpmn.io)</td><td>Mapeamento do processo</td><td>Padrão de mercado; abre no Camunda Modeler.</td></tr>
</table>

<h2>5. Regras de negócio, decisões e processamento</h2>
<h3>Decisão 1 — a chuva justifica agir?</h3>
<table><tr><th>Condição (próximas 24h)</th><th>Nível</th><th>Consequência</th></tr>
<tr><td>chuva ≥ 50 mm</td><td><b>ALERTA</b></td><td>OS para prioridades CRÍTICA, ALTA e MÉDIA; alerta a todas as áreas com risco ≥ 2</td></tr>
<tr><td>chuva ≥ 20 mm <i>ou</i> pico ≥ 10 mm/h com probabilidade ≥ 60%</td><td><b>ATENÇÃO</b></td><td>OS para CRÍTICA e ALTA; alerta só às áreas com bueiro CRÍTICO</td></tr>
<tr><td>abaixo dos limites</td><td>NORMAL</td><td>registra a execução e encerra sem ação</td></tr></table>
<h3>Score de prioridade (0–100) por boca de lobo</h3>
<p><code>score = 0,5 × obstrução% + 0,3 × (risco da área ÷ 3 × 100) + 0,2 × (min(alagamentos em 5 anos, 10) × 10)</code><br>
Faixas: <b>CRÍTICA ≥ 70 · ALTA ≥ 50 · MÉDIA ≥ 30 · BAIXA &lt; 30</b>. Ex.: BL-001, 92% obstruída no Jardim Pantanal
(risco 3, 9 alagamentos) → 46 + 30 + 18 = <b>94 (CRÍTICA)</b>.</p>
<h3>Demais decisões</h3>
<ul>
<li>Obstrução &lt; 30% → não gera OS (“sem necessidade”).</li>
<li>Inspeção com mais de 7 dias ou confiança da visão computacional &lt; 0,6 → OS marcada para <b>reinspeção</b>.</li>
<li>Bueiro sem inspeção válida → pedido de nova ronda do robô (aviso no log).</li>
<li>Distribuição: equipes com capacidade (3 × 5 bueiros); prioriza a equipe que já atende a mesma área; acabou a capacidade →
<b>AGUARDANDO_REFORCO</b> e aviso à operação.</li>
<li>Status final: <code>CONCLUIDO</code>, <code>CONCLUIDO_COM_PENDENCIAS</code> (rejeições/excedentes), <code>SEM_ACAO</code>,
<code>FALHA_PREVISAO</code>, <code>FALHA_DADOS</code>, <code>FALHA</code>.</li></ul>
<h3>Estruturas de repetição (processamento em lote)</h3>
<p>Loop por arquivo de inspeção → loop por linha (validação/deduplicação) → loop por bueiro do cadastro (score e decisão)
→ loop por OS (equipes) → loop por área e por morador (alertas).</p>

<h2>6. Tratamento de exceções e recuperação</h2>
<table><tr><th>Falha</th><th>Tratamento / recuperação</th></tr>
<tr><td>API fora do ar, timeout, HTTP ≠ 200</td><td>3 tentativas com backoff exponencial (1 s, 2 s)</td></tr>
<tr><td>Resposta inválida (HTML, JSON incompleto, &lt; 12 h de dados, valor negativo)</td><td>Tratada como falha → nova tentativa</td></tr>
<tr><td>API indisponível após as tentativas</td><td>Usa o <b>cache</b> da última previsão se tiver menos de 24 h</td></tr>
<tr><td>Sem API e sem cache válido</td><td><b>Falha controlada</b>: <code>FALHA_PREVISAO</code>, código 2, notificação à operação</td></tr>
<tr><td>Arquivo de inspeção com colunas erradas / ilegível</td><td>Arquivo ignorado e registrado na quarentena; os demais seguem</td></tr>
<tr><td>Linha inválida (obstrução vazia, &gt; 100, não numérica; data inválida ou futura; bueiro não cadastrado)</td><td>Linha rejeitada com motivo; lote continua</td></tr>
<tr><td>Dados duplicados</td><td>Linha idêntica descartada; bueiro repetido → mantém a inspeção mais recente</td></tr>
<tr><td>Nenhuma inspeção válida / cadastro ausente</td><td><code>FALHA_DADOS</code>, código 3, notificação à operação</td></tr>
<tr><td>Bot reexecutado no mesmo dia</td><td><b>Idempotência</b>: chave hash (data + destinatário + área + nível) impede alerta repetido</td></tr>
<tr><td>Webhook da operação fora</td><td>3 tentativas; falha contada no resumo sem derrubar o bot</td></tr>
<tr><td>Erro inesperado</td><td>Capturado, logado, status <code>FALHA</code>, código 1 — nunca falha silenciosa</td></tr></table>
<p>Exemplo real da quarentena (<code>output/quarentena/</code>) na demonstração de 75 mm:</p>
<pre>{trecho("tests/evidencias/06_sucesso_alerta.txt", ["rejeitado", "ignorado"], 8)}</pre>

<h2>7. Logs e evidências de auditoria</h2>
<p>Cada execução recebe um <code>execucao_id</code>. Os eventos vão para <code>logs/bot_AAAAMMDD.jsonl</code> (data/hora, nível,
etapa, mensagem, dados) e o resumo para a tabela <code>execucoes</code>: itens lidos, válidos, rejeitados, duplicados, OS,
excedentes, alertas enviados/ignorados e falhas. Telefones e e-mails nunca são gravados (mascaramento + filtro de segurança).</p>
<pre>{log_json}</pre>
<pre>{trecho("tests/evidencias/06_sucesso_alerta.txt", ["[decisao]", "BL-001 ", "BL-005 ", "BL-023 ", "ordem(ns)", "Capacidade", "sem inspeção", "Áreas", "LGPD", "alerta(s) enviado", "[fim]"], 12)}</pre>

<h2 class="quebra">8. Integração com o MVP</h2>
<table><tr><th>Via</th><th>Artefato</th><th>Consumidor</th></tr>
<tr><td>Banco de dados</td><td><code>output/citizentech.db</code> — tabelas <code>execucoes</code>, <code>ordens_servico</code>, <code>alertas</code></td><td>Back-end CitizenTech</td></tr>
<tr><td>Arquivos estruturados</td><td><code>output/api/ultimo_resultado.json</code>, <code>output/ordens_servico_*.csv</code>, <code>output/outbox/*.jsonl</code></td><td>App das equipes, BI, gateway de SMS/WhatsApp</td></tr></table>
<h3>API REST (contrato completo em <code>docs/openapi.yaml</code>)</h3>
<table><tr><th>Rota</th><th>Função</th><th>Consumidor</th></tr>
<tr><td><code>GET /api/status</code></td><td>Última execução: nível, chuva prevista, contadores</td><td>Dashboard</td></tr>
<tr><td><code>GET /api/ordens</code> (<code>?prioridade=&amp;equipe=&amp;area=&amp;status=</code>)</td><td>Lista priorizada de bocas de lobo</td><td>App das equipes, dashboard</td></tr>
<tr><td><code>GET /api/ordens/{{id_bueiro}}</code></td><td>Ordem de serviço de um bueiro</td><td>App das equipes</td></tr>
<tr><td><code>GET /api/alertas/publico</code></td><td>Alerta vigente por área, sem dados pessoais</td><td>App do cidadão</td></tr>
<tr><td><code>GET /api/alertas</code>, <code>/api/pendencias</code>, <code>/api/execucoes</code></td><td>Alertas (contatos mascarados), pendências, auditoria</td><td>Operação / Defesa Civil</td></tr>
<tr><td><code>POST /api/inspecoes</code> 🔑</td><td>Recebe a ronda do carrinho (JSON) e grava em <code>data/inspecoes/</code></td><td>Carrinho / robô de inspeção</td></tr>
<tr><td><code>POST /api/executar</code> 🔑</td><td>Executa o bot sob demanda (<code>{{"simular_chuva": 75}}</code>)</td><td>Operação</td></tr></table>
<p>🔑 exige o cabeçalho <code>x-api-key</code> quando <code>API_TOKEN</code> está configurado. A lógica da API
(<code>src/bocadelobo/api_core.py</code>) não depende do ambiente: roda localmente (<code>python src/api.py</code>) e já está
preparada para AWS (API Gateway + Lambda + S3, pasta <code>aws/</code>).</p>
<figure>{img("assets/dashboard_mvp.png")}<figcaption>Figura 2 — Dashboard do MVP consumindo a API do bot: nível, KPIs, mapa de prioridade, alertas, lista de limpeza e histórico.</figcaption></figure>
<figure>{img("assets/api_ordens_json.png", "width:80%;display:block;margin:auto")}<figcaption>Figura 3 — Resposta da rota <code>GET /api/ordens</code>.</figcaption></figure>

<h2 class="quebra">9. Testes realizados (sucesso, decisão e falha)</h2>
<p>46 testes automatizados em <code>tests/test_bot.py</code> e <code>tests/test_api.py</code> e <code>tests/test_publicacao.py</code> (<code>python -m unittest discover -s tests -v</code>) —
<b>46/46 aprovados</b>. Cada teste roda numa pasta temporária, com data de referência fixa. Execuções manuais registradas em
<code>tests/evidencias/</code>:</p>
<table><tr><th>Tipo</th><th>Cenário</th><th>Resultado esperado</th><th>Obtido</th></tr>
<tr><td>Sucesso</td><td>Simulação 75 mm</td><td>ALERTA, OS priorizadas, alertas, integração MVP</td><td>✔ 19 OS (11 críticas), 4 aguardando reforço, 17 alertas, JSON/banco gerados</td></tr>
<tr><td>Sucesso</td><td>Previsão real Open-Meteo</td><td>Consulta, cache salvo, decisão</td><td>✔ 0,2 mm → NORMAL</td></tr>
<tr><td>Decisão</td><td>Simulação 5 mm</td><td>SEM_ACAO</td><td>✔ 0 OS, 0 alertas</td></tr>
<tr><td>Decisão</td><td>Simulação 30 mm</td><td>ATENÇÃO, sem prioridade MÉDIA</td><td>✔ 17 OS, nenhuma MÉDIA</td></tr>
<tr><td>Decisão</td><td>Pancada 11 mm/h com 80% / 30%</td><td>ATENÇÃO / NORMAL</td><td>✔</td></tr>
<tr><td>Decisão</td><td>Limites 20 mm e 50 mm</td><td>Limites inclusivos</td><td>✔</td></tr>
<tr><td>Falha</td><td>API fora (com cache)</td><td>3 tentativas → cache</td><td>✔</td></tr>
<tr><td>Falha</td><td>API fora (sem cache)</td><td>FALHA_PREVISAO, código 2, operação notificada</td><td>✔</td></tr>
<tr><td>Falha</td><td>Cache expirado / resposta HTML</td><td>Descartado / tratado como falha</td><td>✔</td></tr>
<tr><td>Falha</td><td>Dados inválidos e duplicados</td><td>Quarentena com motivo</td><td>✔ 7 linhas + 1 arquivo</td></tr>
<tr><td>Falha</td><td>Sem arquivos de inspeção</td><td>FALHA_DADOS, código 3</td><td>✔</td></tr>
<tr><td>Resiliência</td><td>Reexecução no mesmo dia</td><td>Nenhum alerta repetido</td><td>✔ 0 enviados, 17 ignorados</td></tr>
<tr><td>LGPD</td><td>Morador sem consentimento / logs</td><td>Não recebe / sem telefone e e-mail</td><td>✔</td></tr></table>
<pre>{trecho("tests/evidencias/00_testes_automatizados.txt", ["... ok", "Ran ", "OK"], 30)}</pre>

<h2>10. Considerações de segurança e LGPD</h2>
<ul>
<li><b>Finalidade e base legal:</b> dados do morador usados só para alertas de risco — consentimento (art. 7º, I) e proteção da vida e
da incolumidade física (art. 7º, VII).</li>
<li><b>Consentimento:</b> o bot só alerta quem tem <code>consentimento_lgpd = sim</code> (2 moradores da base de exemplo são pulados).</li>
<li><b>Minimização:</b> logs, banco e saídas identificam o morador só pelo ID; contato aparece mascarado (<code>(11) 9****-**72</code>).</li>
<li><b>Filtro de segurança</b> nos logs remove qualquer telefone ou e-mail que escape (verificado em teste automatizado).</li>
<li><b>Segredos</b> (URL do webhook) só em variável de ambiente / GitHub Secrets.</li>
<li><b>API somente leitura</b>; a rota pública <code>/api/alertas/publico</code> não tem dados pessoais.</li>
<li><b>Dados de exemplo fictícios</b> — nomes, telefones e endereços inventados.</li>
<li><b>Em produção:</b> HTTPS e autenticação na API, criptografia do banco, retenção de logs por 90 dias, opção de descadastro.</li></ul>

<h2>11. Links</h2>
<table><tr><th>Repositório GitHub</th><td>{html.escape(eq['link_github'])}</td></tr>
<tr><th>Vídeo demonstrativo</th><td>{html.escape(eq['link_video'])}</td></tr></table>
</body></html>"""

saida_html = DOCS / "relatorio.html"
saida_html.write_text(HTML, encoding="utf-8")
navegadores = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
               r"C:\Program Files\Google\Chrome\Application\chrome.exe",
               shutil.which("chromium") or "", shutil.which("google-chrome") or ""]
nav = next((n for n in navegadores if n and Path(n).exists()), None)
if not nav:
    raise SystemExit("Edge/Chrome não encontrado: abra docs/relatorio.html no navegador e imprima em PDF.")
pdf = DOCS / "Relatorio_Tecnico_RPA.pdf"
subprocess.run([nav, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}", saida_html.as_uri()], check=True, capture_output=True)
print(f"PDF gerado: {pdf}")
