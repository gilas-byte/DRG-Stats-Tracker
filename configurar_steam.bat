@echo off
rem ============================================================
rem  configurar_steam.bat
rem  Monta a linha das LAUNCH OPTIONS da Steam com o caminho
rem  DESTE PC e copia pro clipboard. Voce so cola na Steam.
rem
rem  Como usar:
rem    1) De duplo clique neste arquivo.
rem    2) Steam -> DRG -> botao direito -> Propriedades ->
rem       Geral -> Opcoes de Inicializacao.
rem    3) Cole com Ctrl+V (ja esta no clipboard) e feche.
rem
rem  %~dp0 = a pasta deste .bat (com barra no fim). Assim o
rem  caminho sai certo em qualquer computador, sem digitar nada.
rem ============================================================
setlocal

set "PASTA=%~dp0"

echo(
echo  Linha para colar nas Opcoes de Inicializacao da Steam:
echo(
echo     "%PASTA%drg_watcher_launch.bat" %%command%%
echo(

rem Escreve a linha num arquivo temporario e joga pro clipboard via 'clip'
rem (arquivo evita o espaco/quebra que o 'echo ... | clip' costuma deixar).
> "%TEMP%\_steam_line.txt" echo "%PASTA%drg_watcher_launch.bat" %%command%%
clip < "%TEMP%\_steam_line.txt"
del "%TEMP%\_steam_line.txt"

echo  ^>^> Copiado pro clipboard! Cole na Steam com Ctrl+V.
echo(
pause
