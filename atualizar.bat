@echo off
REM ==========================================================================
REM  atualizar.bat  --  DOUBLE-CLICK here to update the project.
REM  It downloads the newest code from GitHub (git pull) WITHOUT touching your
REM  personal data: drg_stats.db, watcher.log and the .sav files are gitignored,
REM  so your history/snapshots are safe.
REM  Requirements: Git installed AND the project obtained via "git clone"
REM  (the ZIP download does NOT support updates).
REM ==========================================================================
title DRG Stats Tracker - Atualizar
cd /d "%~dp0"

echo.
echo   ============================================
echo      DRG Stats Tracker - procurando updates...
echo   ============================================
echo.

REM --- Is Git installed? ---
where git >nul 2>nul
if errorlevel 1 (
    echo   [ERRO] Git nao encontrado.
    echo   Instale o Git em https://git-scm.com/download/win
    echo   ^(depois de instalar, feche e abra esta janela de novo^)
    echo.
    pause
    exit /b 1
)

REM --- Is this folder a git clone? (ZIP downloads are not) ---
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo   [ERRO] Esta pasta nao e um clone do repositorio.
    echo   Voce provavelmente baixou o ZIP. Para receber atualizacoes,
    echo   pegue o projeto assim ^(uma vez so^):
    echo       git clone https://github.com/gilas-byte/DRG-Stats-Tracker
    echo.
    pause
    exit /b 1
)

echo   Baixando as novidades do GitHub...
echo.
git pull
if errorlevel 1 (
    echo.
    echo   [ERRO] Nao consegui atualizar. Pode ser falta de internet, ou
    echo   voce editou algum arquivo do projeto ^(gerando conflito^).
    echo.
    pause
    exit /b 1
)

echo.
echo   ============================================
echo      Pronto! Projeto atualizado.
echo      ^(Se o painel estava aberto, feche e abra de novo.^)
echo   ============================================
echo.
pause
