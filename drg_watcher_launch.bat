@echo off
rem ============================================================
rem  Lancador: sobe o vigia (watcher.py) escondido e depois o
rem  jogo. Vai nas LAUNCH OPTIONS da Steam exatamente assim:
rem
rem      "C:\...\Papaio-Stats\drg_watcher_launch.bat" %command%
rem
rem  %~dp0 = a pasta deste .bat (acha o watcher.py do lado).
rem  %*    = tudo que a Steam passou (= %command% = o jogo).
rem ============================================================

rem 1) sobe o vigia escondido, sem travar este .bat (start = destaca)
start "" /min pythonw "%~dp0watcher.py"

rem 2) lanca o jogo e SEGURA enquanto ele roda (a Steam espera isto)
%*
