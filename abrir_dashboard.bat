@echo off
REM ==========================================================================
REM  abrir_dashboard.bat  --  DOUBLE-CLICK here to open the DRG panel.
REM  No programming needed: this file handles everything.
REM    1) checks whether Python is installed;
REM    2) installs Streamlit the first time (only once);
REM    3) opens the panel in your browser.
REM  To close it later: come back to this black window and press Ctrl+C, or just close it.
REM ==========================================================================
title DRG Stats Tracker
cd /d "%~dp0"

echo.
echo   ============================================
echo      DRG Stats Tracker - abrindo o painel...
echo   ============================================
echo.

REM --- Find Python (try the "py" launcher, then "python") ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo   [ERRO] Python nao encontrado.
    echo   Instale o Python 3.10+ em https://www.python.org/downloads/
    echo   IMPORTANTE: marque a caixa "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

REM --- Is Streamlit installed? If not, install it (only happens the 1st time) ---
%PY% -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo   Primeira vez: instalando o Streamlit ^(pode demorar 1-2 min^)...
    echo.
    %PY% -m pip install --quiet --upgrade streamlit
    if errorlevel 1 (
        echo.
        echo   [ERRO] Falha ao instalar o Streamlit. Verifique sua internet.
        pause
        exit /b 1
    )
)

echo   Abrindo no navegador... deixe esta janela preta ABERTA enquanto usa.
echo.
%PY% -m streamlit run dashboard.py

pause
