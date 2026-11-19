@echo off
rem Abre o painel do MVP (com a Central do robo) no navegador. Duplo clique para usar.
rem A janela minimizada e o servidor local: feche-a para encerrar o painel.
cd /d "%~dp0"
where py >nul 2>nul && (start "Boca de Lobo - servidor do painel" /min py src\api.py --abrir) || (start "Boca de Lobo - servidor do painel" /min python src\api.py --abrir)
