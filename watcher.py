#!/usr/bin/env python3
"""
watcher.py — the Deep Rock Galactic save "watcher".

The idea (and the WHY behind it)
--------------------------------
You don't want to keep running snapshot.py by hand. So this script keeps an eye on
the save file and takes a snapshot ON ITS OWN at the right moments:

  1. when the game OPENS         -> initial snapshot (the session baseline);
  2. when the save is REWRITTEN  -> DRG rewrites the .sav when you finish a mission
     (back to the Space Rig), so the file's modified date changes -> snapshot;
  3. when the game CLOSES        -> final snapshot and the watcher exits on its own.

How this becomes "truly automatic": you put this watcher in Steam's LAUNCH OPTIONS,
in front of the game. That way it starts alongside DRG and dies with it:

    cmd /c start "" /min pythonw "C:\\...\\watcher.py" & %command%

The `%command%` is the game itself (Steam substitutes it). `pythonw` runs with no
window. Result: the player just clicks Play; the history fills up on its own.

Why it does NOT bloat the database: snapshot.tirar_snapshot() already has DEDUP — if
nothing changed since the last snapshot (same kills and same time), it does NOT write.
So even though the save changes all the time, a new row only appears when something
actually changed.

Detecting "game open/closed"
----------------------------
On Windows, we ask the OS whether the DRG process (FSD-Win64-Shipping.exe) is running,
via `tasklist`. On Linux, we try `pgrep`. If the process can't be detected (odd OS),
the watcher falls back to "file mode": it just watches the .sav and runs until you
close it with Ctrl+C (or until --minutos runs out).

Usage:
    python watcher.py                 # find the save, wait for the game, watch
    python watcher.py "/path.sav"     # point to the save manually
    python watcher.py --intervalo 5   # check every 5 seconds (default: 8)
    python watcher.py --sem-processo  # ignore game detection (run until Ctrl+C)
    python watcher.py --minutos 60    # in file mode, stop after 60 min

Requires snapshot.py and drg_save_parser.py in the same folder. Stdlib only.
"""

import sys
import os
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

import snapshot   # reuses find_save / load_names / conectar / tirar_snapshot

# ------------------------------- configuration ------------------------------
# The DRG process name on Windows. It's how we know whether the game is open.
# (On Linux via Proton the name is usually the same, running under wine.)
GAME_PROCESS = "FSD-Win64-Shipping.exe"

INTERVALO_PADRAO = 8      # how many seconds between checks
ESPERA_ESCRITA   = 4      # after seeing the save change, wait for DRG to FINISH writing
ESPERA_JOGO      = 180    # how long to wait for the game to appear before giving up

LOG_PATH = "watcher.log"  # the watcher's history (next to the database)

# WINDOWS GOTCHA: when the watcher runs via pythonw (no console), each call to
# `tasklist` opens a little console WINDOW that FLASHES and STEALS FOCUS from the
# active window. The CREATE_NO_WINDOW flag (0x08000000) tells it to create the child
# process with no window at all, killing the flicker. Windows only.
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0


# ------------------------------- utilities ----------------------------------
def log(msg: str):
    """
    Record a timestamped line. ALWAYS writes to a UTF-8 file (so emoji and accents
    never break) and, ONLY IF possible, also to the console.

    Why so much care: the watcher runs via `pythonw` (no window), where `sys.stdout`
    can be None; and on the Windows console (cp1252) an emoji throws a
    UnicodeEncodeError. Logging to a file solves both at once.
    """
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass
    if sys.stdout is not None:                       # None under pythonw
        try:
            print(linha, flush=True)
        except (UnicodeEncodeError, ValueError, OSError):
            pass                                     # console couldn't handle it; that's fine


def jogo_rodando():
    """
    Return True/False whether the DRG process is active, or None if we can't tell on
    this OS (then the caller falls back to file mode).
    """
    try:
        if sys.platform == "win32":
            # /FI filters by name; if found, the name shows up in the output.
            saida = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}"],
                capture_output=True, text=True, timeout=10,
                creationflags=_SEM_JANELA,      # <- no flashing little window
            ).stdout
            return GAME_PROCESS.lower() in saida.lower()
        else:
            # Linux/macOS: pgrep returns code 0 if it found any process.
            r = subprocess.run(
                ["pgrep", "-f", GAME_PROCESS],
                capture_output=True, timeout=10,
            )
            return r.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None      # no detection tool -> "don't know"


def tirar_foto(save_path: Path, names: dict, motivo: str):
    """
    Open the database, try to store a snapshot, and close it. Opening/closing per
    snapshot (instead of keeping the connection open) avoids holding the database
    file, so the dashboard can read it just fine in parallel.
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


# ------------------------------- main loop -----------------------------------
def vigiar(save_path: Path, names: dict, intervalo: int,
           usar_processo: bool, limite_minutos: int | None):
    log(f"Vigia iniciado. Save: {save_path}")

    # 1) Opening snapshot: the save already reflects the last session; it's our baseline.
    tirar_foto(save_path, names, "abertura")

    try:
        ultimo_mtime = save_path.stat().st_mtime
    except OSError:
        ultimo_mtime = 0

    # If the OS can't detect the process, force file mode.
    if usar_processo and jogo_rodando() is None:
        log("Não consigo detectar o processo do jogo neste SO — indo pro modo "
            "arquivo (encerre com Ctrl+C).")
        usar_processo = False

    jogo_ja_apareceu = False
    esperando_jogo = 0
    inicio = time.time()

    while True:
        time.sleep(intervalo)

        # --- (A) did the save change? (mission end, forge purchase, etc.) ---
        try:
            mtime = save_path.stat().st_mtime
        except OSError:
            mtime = ultimo_mtime          # file vanished for a moment; ignore
        if mtime != ultimo_mtime:
            # DRG might still be WRITING the file. Wait for it to settle and re-read
            # the mtime, so we don't read a half-written save.
            time.sleep(ESPERA_ESCRITA)
            try:
                ultimo_mtime = save_path.stat().st_mtime
            except OSError:
                ultimo_mtime = mtime
            tirar_foto(save_path, names, "save alterado")

        # --- (B) process logic: starts with the game, dies with it ---
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
                # game hasn't opened yet: give Steam/DRG some time to load
                esperando_jogo += intervalo
                if esperando_jogo >= ESPERA_JOGO:
                    log("O jogo não apareceu a tempo — encerrando o vigia.")
                    break

        # --- (C) file mode: stop at the minute limit, if any ---
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

    # Steam may launch the watcher with the GAME's working directory, not ours.
    # Anchoring to the script's own folder ensures 'drg_stats.db',
    # 'all_drg_enemies.json' and 'watcher.log' land in the right place.
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
