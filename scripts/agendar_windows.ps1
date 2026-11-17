# Agenda o bot no Agendador de Tarefas do Windows para rodar todo dia às 06:00.
# Uso (PowerShell):  .\scripts\agendar_windows.ps1
$raiz = Split-Path -Parent $PSScriptRoot
$acao = New-ScheduledTaskAction -Execute "py" -Argument "src\main.py" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -Daily -At 6:00am
Register-ScheduledTask -TaskName "CitizenTech-BocaDeLobo" -Action $acao -Trigger $gatilho `
    -Description "Bot RPA Boca de Lobo - previsão de chuva, priorização de limpeza e alertas" -Force
Write-Host "Tarefa 'CitizenTech-BocaDeLobo' agendada para 06:00 diariamente."
