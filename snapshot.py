#!/usr/bin/env python3
"""
snapshot.py — takes a "snapshot" of your Deep Rock Galactic stats and stores it in
a local SQLite database. Run it now and then and you build up a HISTORY — you can
see how many grunts you killed this week, credit progression, playtime, etc.

Built to work even for someone who just installed it:
  - finds the save on its own in the standard Steam paths (Windows and Linux);
  - creates the database and tables on first run (nothing to configure);
  - no duplicates: if nothing changed since the last snapshot, it doesn't write again;
  - if all_drg_enemies.json exists, it uses the names; if not, it stores by GUID.

Usage:
    python snapshot.py                  # find the save and take a snapshot
    python snapshot.py "/path.sav"      # point to the save manually
    python snapshot.py --loop 30        # take a snapshot every 30 minutes
    DRG_SAVE=/path.sav python snapshot.py   # via environment variable

Requires drg_save_parser.py in the same folder.
"""

import sys
import os
import re
import glob
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import drg_save_parser as drg

# ------------------------------- configuration ------------------------------
DB_PATH = "drg_stats.db"
NAMES_PATH = "all_drg_enemies.json"        # optional; if missing, that's fine
GUIDS_PATH = "guids.json"                  # overclock catalog; optional

# Paths where the save usually lives. Accepts wildcards (*) and OS variables.
SAVE_GLOBS = [
    # Windows / Steam
    r"%ProgramFiles(x86)%\Steam\steamapps\common\Deep Rock Galactic\FSD\Saved\SaveGames\*_Player.sav",
    r"%ProgramFiles%\Steam\steamapps\common\Deep Rock Galactic\FSD\Saved\SaveGames\*_Player.sav",
    # Linux / Steam (native, and Flatpak)
    "~/.steam/steam/steamapps/common/Deep Rock Galactic/FSD/Saved/SaveGames/*_Player.sav",
    "~/.local/share/Steam/steamapps/common/Deep Rock Galactic/FSD/Saved/SaveGames/*_Player.sav",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Deep Rock Galactic/FSD/Saved/SaveGames/*_Player.sav",
]
# ----------------------------------------------------------------------------


# The database schema. "IF NOT EXISTS" makes this IDEMPOTENT: running it a thousand
# times equals running it once. That's what lets a new user just run the script.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at         TEXT    NOT NULL,      -- ISO 8601 date/time (UTC)
    save_file        TEXT,                  -- which file it came from
    level            INTEGER,
    credits          INTEGER,
    perk_points      INTEGER,
    games_played     INTEGER,
    missions_completed INTEGER,
    times_retired    INTEGER,
    playtime_seconds REAL,
    total_kills      INTEGER,
    overclocks_forged INTEGER            -- weapon OCs forged (crossed with guids.json)
);

-- One row per species PER snapshot. We store the GUID (the stable key that ALWAYS
-- exists) and the name only as enrichment (may be NULL). That way even an enemy
-- with no mapped name is tracked, and the name can be filled in later.
CREATE TABLE IF NOT EXISTS kills (
    snapshot_id  INTEGER NOT NULL,
    guid         TEXT    NOT NULL,
    name         TEXT,
    count        INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, guid),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kills_guid      ON kills(guid);
CREATE INDEX IF NOT EXISTS idx_snapshots_taken ON snapshots(taken_at);
"""


# The save's path fragment INSIDE any Steam library.
SAVE_SUBPATH = os.path.join(
    "steamapps", "common", "Deep Rock Galactic",
    "FSD", "Saved", "SaveGames", "*_Player.sav",
)


def _steam_libraries() -> list:
    """
    Discover the root folders of ALL Steam libraries — including ones on other drives
    (D:, E:...). Steam lists these in `libraryfolders.vdf`. Without this step, someone
    who installed DRG outside C: would have to point to the save by hand.

    Strategy (stdlib only):
      1) find where Steam is installed (registry on Windows; default paths on Linux);
      2) read the libraryfolders.vdf there and extract each "path" (Valve KeyValues format).
    """
    bases = []
    if sys.platform == "win32":
        try:                                    # the REAL Steam path comes from the registry
            import winreg
            tentativas = [
                (winreg.HKEY_CURRENT_USER,  r"Software\Valve\Steam",            "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            ]
            for hive, chave, valor in tentativas:
                try:
                    with winreg.OpenKey(hive, chave) as k:
                        bases.append(winreg.QueryValueEx(k, valor)[0])
                except OSError:
                    pass
        except ImportError:
            pass
        bases += [os.path.expandvars(r"%ProgramFiles(x86)%\Steam"),
                  os.path.expandvars(r"%ProgramFiles%\Steam")]
    else:
        bases += [os.path.expanduser("~/.steam/steam"),
                  os.path.expanduser("~/.local/share/Steam"),
                  os.path.expanduser("~/.var/app/com.valvesoftware.Steam/.local/share/Steam")]

    roots, vistos = [], set()
    def add(p):
        p = str(Path(p))
        if p not in vistos:
            vistos.add(p)
            roots.append(p)

    for base in bases:
        if not base:
            continue
        add(base)                               # the Steam folder itself is a library
        for vdf in (Path(base) / "steamapps" / "libraryfolders.vdf",
                    Path(base) / "config" / "libraryfolders.vdf"):
            try:
                texto = vdf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # extract each:  "path"   "D:\\SteamLibrary"   -> undo the \\ escape -> \
            for m in re.finditer(r'"path"\s*"([^"]+)"', texto):
                add(m.group(1).replace("\\\\", "\\"))
    return roots


def find_save(explicit: str | None = None) -> Path | None:
    """Find the save path: argument > environment variable > automatic search."""
    if explicit:
        return Path(explicit)
    if os.environ.get("DRG_SAVE"):
        return Path(os.environ["DRG_SAVE"])

    achados = []
    # 1) static globs (fast; cover the default C: install)
    for padrao in SAVE_GLOBS:
        achados.extend(glob.glob(os.path.expanduser(os.path.expandvars(padrao))))
    # 2) Steam libraries on ANY drive (via libraryfolders.vdf)
    for root in _steam_libraries():
        achados.extend(glob.glob(str(Path(root) / SAVE_SUBPATH)))

    achados = [Path(a) for a in achados if a.endswith("_Player.sav")]
    if not achados:
        return None
    # if there's more than one profile/install, pick the most recently modified
    return max(achados, key=lambda p: p.stat().st_mtime)


def load_names() -> dict:
    p = Path(NAMES_PATH)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _contar_overclocks(forged) -> int | None:
    """How many WEAPON overclocks are forged: intersect the save's ForgedSchematics
    (overclocks + matrix-core cosmetics, mixed) with the Weapons catalog in guids.json.
    Returns None if guids.json is missing — so we store NULL instead of a fake 0
    (don't fabricate history; the dashboard delta just won't show an arrow)."""
    p = Path(GUIDS_PATH)
    if not p.exists():
        return None
    catalogo = {g.upper() for g in json.loads(p.read_text(encoding="utf-8")).get("Weapons", {})}
    return sum(1 for g in forged if g.upper() in catalogo)


def conectar(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # SQLITE GOTCHA: it does NOT enforce FOREIGN KEY by default. You have to enable it
    # on every connection, otherwise the ON DELETE CASCADE simply doesn't happen.
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_SQL)     # create tables if they don't exist
    _migrar(conn)                      # adjust OLD databases (new columns)
    return conn


def _migrar(conn: sqlite3.Connection):
    """
    Light migration for databases created before a new column existed.
    'CREATE TABLE IF NOT EXISTS' does NOT alter a table that already exists — so a
    column added later would never show up in an old database. Here we check the
    current columns (via PRAGMA) and only run the ALTER TABLE for what's missing.
    It's idempotent: on an already-updated database it does nothing.
    """
    existentes = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
    novas = {"missions_completed": "INTEGER", "overclocks_forged": "INTEGER"}
    for coluna, tipo in novas.items():
        if coluna not in existentes:
            # NOTE: the f-string here is SAFE and necessary. The "never f-string SQL"
            # rule is for VALUES coming from outside (use '?'). But '?' doesn't work for
            # column/type NAMES (identifiers), and these come from a fixed dict in the
            # code — not from user input. So no injection risk.
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {coluna} {tipo}")
    conn.commit()


def _data_local(iso_utc: str):
    """Convert a taken_at (ISO in UTC) into the DATE in the PC's local timezone."""
    return datetime.fromisoformat(iso_utc).astimezone().date()


def tirar_snapshot(conn: sqlite3.Connection, save_path: Path, names: dict, forcar=False):
    """
    Read the save and store the day's snapshot. Returns the snapshot id, or None if
    nothing changed.

    "ONE SNAPSHOT PER DAY" RULE: storing one per mission would flood the database (30
    missions = 30 rows) and pollute the comparison. So:
      - if the last snapshot is from TODAY (local date) -> UPDATE it to the latest state;
      - if it's from another day (or there's none)       -> create a new snapshot.
    That way each day holds the END-of-day state, the database stays light (1 row/day),
    and the day-to-day delta = exactly "what you did that day".
    """
    s = drg.parse_save(str(save_path), enemy_names=names)

    # DEDUP: if the last snapshot has the same kills and time, don't write repeated junk.
    ultimo = conn.execute(
        "SELECT id, total_kills, playtime_seconds, taken_at "
        "FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if ultimo and not forcar:
        mesmo_kills = ultimo[1] == s["total_kills"]
        mesmo_tempo = abs((ultimo[2] or 0) - (s["playtime_seconds"] or 0)) < 1
        if mesmo_kills and mesmo_tempo:
            return None

    # Always use PARAMETERIZED queries (the '?'). Never build SQL with f-strings.
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    valores = (agora, save_path.name, s["level"], s["credits"], s["perk_points"],
               s["games_played"], s["missions_completed"], s["times_retired"],
               s["playtime_seconds"], s["total_kills"],
               _contar_overclocks(s["forged_schematics"]))

    hoje = datetime.now().astimezone().date()
    if ultimo and _data_local(ultimo[3]) == hoje:
        # TODAY's snapshot already exists -> update it (and swap its kills)
        snap_id = ultimo[0]
        conn.execute(
            """UPDATE snapshots SET
                 taken_at=?, save_file=?, level=?, credits=?, perk_points=?,
                 games_played=?, missions_completed=?, times_retired=?,
                 playtime_seconds=?, total_kills=?, overclocks_forged=?
               WHERE id=?""",
            (*valores, snap_id),
        )
        conn.execute("DELETE FROM kills WHERE snapshot_id=?", (snap_id,))
    else:
        # first record of the day (or empty database) -> new snapshot
        cur = conn.execute(
            """INSERT INTO snapshots
               (taken_at, save_file, level, credits, perk_points,
                games_played, missions_completed, times_retired, playtime_seconds,
                total_kills, overclocks_forged)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            valores,
        )
        snap_id = cur.lastrowid

    linhas = [(snap_id, guid, names.get(guid), count)
              for guid, count in s["kills_by_guid"].items()]
    conn.executemany(
        "INSERT INTO kills (snapshot_id, guid, name, count) VALUES (?,?,?,?)",
        linhas,
    )
    conn.commit()          # all together: either snapshot + kills are stored, or nothing
    return snap_id


def mostrar_deltas(conn: sqlite3.Connection):
    """Show what grew the most since the previous snapshot — the point of the history.

    Note: the 'how much it grew' is COMPUTED on the fly, with a JOIN between the two
    latest snapshots. We don't store the delta in the database; we store the facts
    (the counts) and derive the rest in the query.
    """
    ids = conn.execute(
        "SELECT id FROM snapshots ORDER BY id DESC LIMIT 2"
    ).fetchall()
    if len(ids) < 2:
        return
    atual, anterior = ids[0][0], ids[1][0]
    rows = conn.execute(
        """SELECT COALESCE(k2.name, 'GUID:'||substr(k2.guid,1,8)) AS especie,
                  k2.count - COALESCE(k1.count, 0) AS delta
           FROM kills k2
           LEFT JOIN kills k1
                  ON k1.guid = k2.guid AND k1.snapshot_id = ?
           WHERE k2.snapshot_id = ?
           ORDER BY delta DESC
           LIMIT 5""",
        (anterior, atual),
    ).fetchall()
    grew = [(nome, d) for nome, d in rows if d > 0]
    if grew:
        print("  Mais mataram desde a última foto:")
        for nome, d in grew:
            print(f"     +{d:<6,} {nome}")


def uma_rodada(db_path: str, save_path: Path, names: dict, forcar=False):
    conn = conectar(db_path)
    try:
        snap_id = tirar_snapshot(conn, save_path, names, forcar=forcar)
        if snap_id is None:
            print("  Nada mudou desde a última foto — nada gravado.")
            return
        total = conn.execute(
            "SELECT total_kills FROM snapshots WHERE id = ?", (snap_id,)
        ).fetchone()[0]
        n = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        print(f"  Snapshot #{snap_id} gravado. Fotos no banco: {n}. Total de kills: {total:,}")
        mostrar_deltas(conn)
    finally:
        conn.close()


def main():
    args = [a for a in sys.argv[1:] if a]
    loop_min = None
    if "--loop" in args:
        i = args.index("--loop")
        loop_min = float(args[i + 1])
        del args[i:i + 2]
    forcar = "--force" in args
    args = [a for a in args if a != "--force"]

    save_path = find_save(args[0] if args else None)
    if save_path is None or not save_path.exists():
        print("Não encontrei o save automaticamente.")
        print("Passe o caminho:  python snapshot.py \"C:\\...\\XXXXX_Player.sav\"")
        print("ou defina a variável DRG_SAVE com o caminho.")
        sys.exit(1)

    names = load_names()
    print(f"Save: {save_path}")
    print(f"Banco: {Path(DB_PATH).resolve()}")
    print(f"Nomes carregados: {len(names)}")

    if loop_min:
        print(f"Modo loop: uma foto a cada {loop_min:g} min (Ctrl+C pra parar)\n")
        try:
            while True:
                print(datetime.now().strftime("[%H:%M:%S]"))
                uma_rodada(DB_PATH, save_path, names, forcar)
                time.sleep(loop_min * 60)
        except KeyboardInterrupt:
            print("\nParado. Rock and Stone!")
    else:
        uma_rodada(DB_PATH, save_path, names, forcar)


if __name__ == "__main__":
    main()
