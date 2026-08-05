@echo off
REM ==========================================================================
REM  atualizar.bat  --  DOUBLE-CLICK here to update the project.
REM  It downloads the newest code from GitHub and overlays it, WITHOUT touching
REM  your personal data (drg_stats.db, *.sav and watcher.log are not in the repo
REM  ZIP, so the update never overwrites them).
REM  NO git needed anymore -- only Python (already required by the project).
REM
REM  MAINTAINER NOTE: the updater (atualizar.py) overwrites THIS file. To stay
REM  self-modify-safe, the last line runs Python and then "& exit /b" quits cmd
REM  in the SAME already-parsed line -- so cmd never re-reads this file after the
REM  download. atualizar.py does its own "press Enter" pause. Keep it that way.
REM ==========================================================================
title DRG Stats Tracker - Atualizar
cd /d "%~dp0"

REM --- Find Python (try the "py" launcher, then "python") ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo   [ERRO] Python nao encontrado.
    echo   Instale o Python 3.10+ em https://www.python.org/downloads/
    echo   IMPORTANTE: marque a caixa "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

REM --- Run the updater. Keep "& exit /b" so cmd quits without re-reading this
REM --- (possibly just-overwritten) file. Nothing may go after this line.
%PY% atualizar.py & exit /b
