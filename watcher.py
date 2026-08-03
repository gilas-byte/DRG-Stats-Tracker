#!/usr/bin/env python3
"""
watcher.py — o "vigia" do save do Deep Rock Galactic.

A ideia (e o PORQUÊ dela)
-------------------------
Você não quer ficar rodando o snapshot.py na mão. Então este script fica de olho
no arquivo de save e tira uma foto SOZINHO nos momentos certos:

  1. quando o jogo ABRE           -> foto inicial (baseline da sessão);
  2. quando o save é REESCRITO    -> o DRG regrava o .sav ao terminar uma missão
     (voltar pro Space Rig), então a data de modificação do arquivo muda -> foto;
  3. quando o jogo FECHA          -> foto final e o vigia encerra sozinho.

Como isso vira "automático de verdade": coloca-se este vigia nas LAUNCH OPTIONS
da Steam, na frente do jogo. Assim ele sobe junto com o DRG e morre junto:

    cmd /c start "" /min pythonw "C:\\...\\watcher.py" & %command%

O `%command%` é o próprio jogo (a Steam troca por ele). O `pythonw` roda sem
janela. Resultado: o jogador só clica em Jogar; o histórico se enche sozinho.

Por que NÃO pesa o banco: o snapshot.tirar_snapshot() já tem DEDUP — se nada
mudou desde a última foto (mesmos kills e mesmo tempo), ele NÃO grava. Então
mesmo o save mudando toda hora, só entra linha nova quando algo de fato mudou.

Detecção de "jogo aberto/fechado"
---------------------------------
No Windows, a gente pergunta ao SO se o processo do DRG (FSD-Win64-Shipping.exe)
está rodando, via `tasklist`. No Linux, tenta `pgrep`. Se não der pra detectar o
processo (SO estranho), o vigia cai no "modo arquivo": só observa o .sav e roda
até você fechar com Ctrl+C (ou até acabar o --minutos).

Uso:
    python watcher.py                 # acha o save, espera o jogo, vigia
    python watcher.py "/caminho.sav"  # aponta o save manualmente
    python watcher.py --intervalo 5   # checa a cada 5 segundos (padrão: 8)
    python watcher.py --sem-processo  # ignora detecção de jogo (roda até Ctrl+C)
    python watcher.py --minutos 60    # no modo arquivo, para depois de 60 min

Depende de snapshot.py e drg_save_parser.py na mesma pasta. Só stdlib.
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

import snapshot   # reaproveita find_save / load_names / conectar / tirar_snapshot

# ------------------------------- configuração -------------------------------
# Nome do processo do DRG no Windows. É por ele que a gente sabe se o jogo está
# aberto. (No Linux via Proton o nome costuma ser o mesmo, rodando sob o wine.)
GAME_PROCESS = "FSD-Win64-Shipping.exe"

INTERVALO_PADRAO = 8      # de quantos em quantos segundos a gente checa
ESPERA_ESCRITA   = 4      # após ver o save mudar, espera o DRG TERMINAR de gravar
ESPERA_JOGO      = 180    # quanto tempo esperar o jogo aparecer antes de desistir

LOG_PATH = "watcher.log"  # histórico do vigia (ao lado do banco)

# PEGADINHA DO WINDOWS: quando o vigia roda via pythonw (sem console), cada
# chamada ao `tasklist` abre uma JANELINHA de console que PISCA e ROUBA O FOCO
# da janela ativa. A flag CREATE_NO_WINDOW (0x08000000) manda criar o processo
# filho sem janela nenhuma, matando o pisca-pisca. Só existe no Windows.
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0


# ------------------------------- utilidades ---------------------------------
def log(msg: str):
    """
    Registra uma linha com hora. Escreve SEMPRE num arquivo UTF-8 (assim emoji e
    acento nunca quebram) e, SÓ SE der, também no console.

    Por que tanto cuidado: o vigia roda via `pythonw` (sem janela), onde
    `sys.stdout` pode ser None; e no console do Windows (cp1252) um emoji dispara
    UnicodeEncodeError. Logar em arquivo resolve os dois de uma vez.
    """
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass
    if sys.stdout is not None:                       # None sob pythonw
        try:
            print(linha, flush=True)
        except (UnicodeEncodeError, ValueError, OSError):
            pass                                     # console não deu conta; tudo bem


def jogo_rodando():
    """
    Devolve True/False se o processo do DRG está ativo, ou None se não dá pra
    saber neste SO (aí o chamador cai no modo arquivo).
    """
    try:
        if sys.platform == "win32":
            # /FI filtra pelo nome; se achar, o nome aparece na saída.
            saida = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}"],
                capture_output=True, text=True, timeout=10,
                creationflags=_SEM_JANELA,      # <- sem janelinha piscando
            ).stdout
            return GAME_PROCESS.lower() in saida.lower()
        else:
            # Linux/macOS: pgrep devolve código 0 se achou algum processo.
            r = subprocess.run(
                ["pgrep", "-f", GAME_PROCESS],
                capture_output=True, timeout=10,
            )
            return r.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None      # sem ferramenta de detecção -> "não sei"


def tirar_foto(save_path: Path, names: dict, motivo: str):
    """
    Abre o banco, tenta gravar uma foto e fecha. Abrir/fechar a cada foto (em vez
    de manter a conexão aberta) evita segurar o arquivo do banco, deixando o
    dashboard ler numa boa em paralelo.
    """
    conn = snapshot.conectar(snapshot.DB_PATH)
    try:
        snap_id = snapshot.tirar_snapshot(conn, save_path, names)
    finally:
        conn.close()
    if snap_id is None:
        log(f"  ({motivo}) nada mudou — dedup, nada gravado.")
    else:
        log(f"  ({motivo}) 📸 foto nova gravada (snapshot #{snap_id}).")
    return snap_id


# ------------------------------- loop principal -----------------------------
def vigiar(save_path: Path, names: dict, intervalo: int,
           usar_processo: bool, limite_minutos: int | None):
    log(f"Vigia iniciado. Save: {save_path}")

    # 1) Foto de abertura: o save já reflete a última sessão; é a nossa baseline.
    tirar_foto(save_path, names, "abertura")

    try:
        ultimo_mtime = save_path.stat().st_mtime
    except OSError:
        ultimo_mtime = 0

    # Se o SO não sabe detectar o processo, força o modo arquivo.
    if usar_processo and jogo_rodando() is None:
        log("Não consigo detectar o processo do jogo neste SO — indo pro modo "
            "arquivo (encerre com Ctrl+C).")
        usar_processo = False

    jogo_ja_apareceu = False
    esperando_jogo = 0
    inicio = time.time()

    while True:
        time.sleep(intervalo)

        # --- (A) o save mudou? (fim de missão, compra na forja, etc.) ---
        try:
            mtime = save_path.stat().st_mtime
        except OSError:
            mtime = ultimo_mtime          # arquivo sumiu por um instante; ignora
        if mtime != ultimo_mtime:
            # O DRG pode ainda estar ESCREVENDO o arquivo. Espera assentar e
            # relê o mtime, pra não ler um save pela metade.
            time.sleep(ESPERA_ESCRITA)
            try:
                ultimo_mtime = save_path.stat().st_mtime
            except OSError:
                ultimo_mtime = mtime
            tirar_foto(save_path, names, "save alterado")

        # --- (B) lógica de processo: sobe junto, morre junto ---
        if usar_processo:
            rodando = jogo_rodando()
            if rodando:
                jogo_ja_apareceu = True
                esperando_jogo = 0
            else:
                if jogo_ja_apareceu:
                    log("Jogo fechado — tirando a foto final.")
                    tirar_foto(save_path, names, "fechamento")
                    break
                # jogo ainda não abriu: dá um tempo pra Steam/DRG carregarem
                esperando_jogo += intervalo
                if esperando_jogo >= ESPERA_JOGO:
                    log("O jogo não apareceu a tempo — encerrando o vigia.")
                    break

        # --- (C) modo arquivo: para no limite de minutos, se houver ---
        elif limite_minutos is not None:
            if (time.time() - inicio) >= limite_minutos * 60:
                log(f"Limite de {limite_minutos} min atingido — encerrando.")
                break

    log("Vigia finalizado.")


def main():
    p = argparse.ArgumentParser(description="Vigia o save do DRG e tira fotos sozinho.")
    p.add_argument("save", nargs="?", help="caminho do .sav (opcional; senão acha sozinho)")
    p.add_argument("--intervalo", type=int, default=INTERVALO_PADRAO,
                   help=f"segundos entre checagens (padrão: {INTERVALO_PADRAO})")
    p.add_argument("--sem-processo", action="store_true", dest="sem_processo",
                   help="ignora a detecção do jogo (roda até Ctrl+C / --minutos)")
    p.add_argument("--minutos", type=int, default=None,
                   help="no modo arquivo, encerra depois de N minutos")
    args = p.parse_args()

    # A Steam pode lançar o vigia com o diretório de trabalho do JOGO, não o
    # nosso. Ancorar na pasta do próprio script garante que 'drg_stats.db',
    # 'all_drg_enemies.json' e 'watcher.log' caiam no lugar certo.
    os.chdir(Path(__file__).resolve().parent)

    save_path = snapshot.find_save(args.save)
    if save_path is None or not save_path.exists():
        log("❌ Não achei o save do DRG. Passe o caminho como argumento ou defina "
            "a variável DRG_SAVE.")
        sys.exit(2)

    names = snapshot.load_names()
    try:
        vigiar(save_path, names, args.intervalo,
               usar_processo=not args.sem_processo,
               limite_minutos=args.minutos)
    except KeyboardInterrupt:
        log("Interrompido (Ctrl+C) — tirando a foto final.")
        tirar_foto(save_path, names, "encerramento manual")


if __name__ == "__main__":
    main()
