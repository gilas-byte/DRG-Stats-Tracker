@echo off
rem ============================================================
rem  configurar_steam.bat
rem  Builds Steam's LAUNCH OPTIONS line with THIS PC's path and
rem  copies it to the clipboard. You just paste it into Steam.
rem
rem  How to use:
rem    1) Double-click this file.
rem    2) Steam -> DRG -> right-click -> Properties ->
rem       General -> Launch Options.
rem    3) Paste with Ctrl+V (already on the clipboard) and close.
rem
rem  %~dp0 = this .bat's folder (with a trailing slash). This way
rem  the path comes out right on any computer, without typing.
rem ============================================================
setlocal

set "PASTA=%~dp0"

echo(
echo  Linha para colar nas Opcoes de Inicializacao da Steam:
echo(
echo     "%PASTA%drg_watcher_launch.bat" %%command%%
echo(

rem Write the line to a temp file and pipe it to the clipboard via 'clip'
rem (a file avoids the trailing space/newline that 'echo ... | clip' tends to leave).
> "%TEMP%\_steam_line.txt" echo "%PASTA%drg_watcher_launch.bat" %%command%%
clip < "%TEMP%\_steam_line.txt"
del "%TEMP%\_steam_line.txt"

echo  ^>^> Copiado pro clipboard! Cole na Steam com Ctrl+V.
echo(
pause
