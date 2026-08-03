@echo off
REM ==========================================================================
REM  Abrir Dashboard.bat  --  DUPLO CLIQUE aqui para abrir o painel do DRG.
REM  Nao precisa saber programar: este arquivo cuida de tudo.
REM    1) confere se o Python esta instalado;
REM    2) instala o Streamlit na primeira vez (so uma vez);
REM    3) abre o painel no seu navegador.
REM  Para fechar depois: volte nesta janela preta e aperte Ctrl+C, ou so feche.
REM ==========================================================================
title DRG Stats Tracker
cd /d "%~dp0"

echo.
echo   ============================================
echo      DRG Stats Tracker - abrindo o painel...
echo   ============================================
echo.

REM --- Acha o Python (tenta o lancador "py" e depois "python") ---
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

REM --- Streamlit instalado? Se nao, instala (so acontece na 1a vez) ---
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
