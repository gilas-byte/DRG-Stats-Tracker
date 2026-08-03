#!/usr/bin/env python3
"""
snapshot.py — tira uma "foto" das suas estatísticas do Deep Rock Galactic e
guarda num banco SQLite local. Rode de tempos em tempos e você acumula um
HISTÓRICO — dá pra ver quantos grunts você matou essa semana, evolução de
créditos, tempo de jogo, etc.

Feito pra funcionar até pra quem acabou de instalar:
  - acha o save sozinho nos caminhos padrão do Steam (Windows e Linux);
  - cria o banco e as tabelas na primeira execução (nada pra configurar);
  - não duplica: se nada mudou desde a última foto, não grava de novo;
  - se o enemy_names.json existir, usa os nomes; se não, guarda pelo GUID mesmo.

Uso:
    python snapshot.py                  # acha o save e tira uma foto
    python snapshot.py "/caminho.sav"   # aponta o save manualmente
    python snapshot.py --loop 30        # tira uma foto a cada 30 minutos
    DRG_SAVE=/caminho.sav python snapshot.py   # via variável de ambiente

Precisa do arquivo drg_save_parser.py na mesma pasta.
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

# ------------------------------- configuração -------------------------------
DB_PATH = "drg_stats.db"
NAMES_PATH = "all_drg_enemies.json"        # opcional; se não existir, tudo bem

# Caminhos onde o save costuma estar. Aceita curingas (*) e variáveis do SO.
SAVE_GLOBS = [
    # Windows / Steam
    r"%ProgramFiles(x86)%\Steam\steamapps\common\Deep Rock Galactic\FSD\Saved\SaveGames\*_Player.sav",
    r"%ProgramFiles%\Steam\steamapps\common\Deep Rock Galactic\FSD\Saved\SaveGames\*_Player.sav",
    # Linux / Steam (nativo, e Flatpak)
    "~/.steam/steam/steamapps/common/Deep Rock Galactic/FSD/Saved/SaveGames/*_Player.sav",
    "~/.local/share/Steam/steamapps/common/Deep Rock Galactic/FSD/Saved/SaveGames/*_Player.sav",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Deep Rock Galactic/FSD/Saved/SaveGames/*_Player.sav",
]
# ----------------------------------------------------------------------------


# O schema do banco. "IF NOT EXISTS" deixa isso IDEMPOTENTE: rodar mil vezes é
# igual a rodar uma. É o que permite um usuário novo só executar o script.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at         TEXT    NOT NULL,      -- data/hora ISO 8601 (UTC)
    save_file        TEXT,                  -- de qual arquivo veio
    level            INTEGER,
    credits          INTEGER,
    perk_points      INTEGER,
    games_played     INTEGER,
    missions_completed INTEGER,
    times_retired    INTEGER,
    playtime_seconds REAL,
    total_kills      INTEGER
);

-- Uma linha por espécie POR snapshot. Guardamos o GUID (chave estável que
-- SEMPRE existe) e o nome só como enriquecimento (pode ser NULL). Assim, mesmo
-- inimigo sem nome mapeado é rastreado, e dá pra preencher o nome depois.
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


# Trecho do caminho do save DENTRO de qualquer biblioteca Steam.
SAVE_SUBPATH = os.path.join(
    "steamapps", "common", "Deep Rock Galactic",
    "FSD", "Saved", "SaveGames", "*_Player.sav",
)


def _steam_libraries() -> list:
    """
    Descobre as pastas-raiz de TODAS as bibliotecas Steam — inclusive as em outros
    drives (D:, E:...). A Steam lista isso no `libraryfolders.vdf`. Sem esse passo,
    quem instalou o DRG fora do C: teria que apontar o save na mão.

    Estratégia (só stdlib):
      1) acha onde a Steam está instalada (registro no Windows; caminhos padrão no Linux);
      2) lê o libraryfolders.vdf de lá e extrai cada "path" (formato KeyValues da Valve).
    """
    bases = []
    if sys.platform == "win32":
        try:                                    # o caminho REAL da Steam vem do registro
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
        add(base)                               # a própria pasta da Steam é uma biblioteca
        for vdf in (Path(base) / "steamapps" / "libraryfolders.vdf",
                    Path(base) / "config" / "libraryfolders.vdf"):
            try:
                texto = vdf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # extrai cada:  "path"   "D:\\SteamLibrary"   -> tira o escape \\ -> \
            for m in re.finditer(r'"path"\s*"([^"]+)"', texto):
                add(m.group(1).replace("\\\\", "\\"))
    return roots


def find_save(explicit: str | None = None) -> Path | None:
    """Descobre o caminho do save: argumento > variável de ambiente > busca automática."""
    if explicit:
        return Path(explicit)
    if os.environ.get("DRG_SAVE"):
        return Path(os.environ["DRG_SAVE"])

    achados = []
    # 1) globs estáticos (rápidos; cobrem a instalação padrão no C:)
    for padrao in SAVE_GLOBS:
        achados.extend(glob.glob(os.path.expanduser(os.path.expandvars(padrao))))
    # 2) bibliotecas Steam em QUALQUER drive (via libraryfolders.vdf)
    for root in _steam_libraries():
        achados.extend(glob.glob(str(Path(root) / SAVE_SUBPATH)))

    achados = [Path(a) for a in achados if a.endswith("_Player.sav")]
    if not achados:
        return None
    # se houver mais de um perfil/instalação, pega o modificado mais recentemente
    return max(achados, key=lambda p: p.stat().st_mtime)


def load_names() -> dict:
    p = Path(NAMES_PATH)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def conectar(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    # PEGADINHA DO SQLITE: ele NÃO respeita FOREIGN KEY por padrão. Tem que ligar
    # em toda conexão, senão o ON DELETE CASCADE simplesmente não acontece.
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_SQL)     # cria tabelas se não existirem
    _migrar(conn)                      # ajusta bancos ANTIGOS (colunas novas)
    return conn


def _migrar(conn: sqlite3.Connection):
    """
    Migração leve pra bancos criados antes de uma coluna nova existir.
    O 'CREATE TABLE IF NOT EXISTS' NÃO altera tabela que já existe — então uma
    coluna adicionada depois nunca apareceria num banco velho. Aqui a gente checa
    as colunas atuais (via PRAGMA) e só roda o ALTER TABLE do que estiver faltando.
    É idempotente: num banco já atualizado, não faz nada.
    """
    existentes = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
    novas = {"missions_completed": "INTEGER"}
    for coluna, tipo in novas.items():
        if coluna not in existentes:
            # OBS: aqui a f-string é SEGURA e necessária. A regra "nunca f-string em SQL"
            # vale pra VALORES vindos de fora (use '?'). Mas '?' não funciona pra NOMES de
            # coluna/tipo (identificadores), e estes vêm de um dict fixo no código — não de
            # input do usuário. Logo, sem risco de injection.
            conn.execute(f"ALTER TABLE snapshots ADD COLUMN {coluna} {tipo}")
    conn.commit()


def _data_local(iso_utc: str):
    """Converte um taken_at (ISO em UTC) pra a DATA no fuso local do PC."""
    return datetime.fromisoformat(iso_utc).astimezone().date()


def tirar_snapshot(conn: sqlite3.Connection, save_path: Path, names: dict, forcar=False):
    """
    Lê o save e grava a foto do dia. Retorna o id do snapshot, ou None se nada mudou.

    REGRA "UMA FOTO POR DIA": guardar uma foto a cada missão encheria o banco (30
    missões = 30 linhas) e deixaria o comparativo poluído. Então:
      - se a última foto é de HOJE (data local) -> ATUALIZA ela pro estado mais recente;
      - se é de outro dia (ou não há nenhuma)    -> cria uma foto nova.
    Assim cada dia guarda o estado do FIM do dia, o banco fica leve (1 linha/dia) e o
    delta de um dia pro outro = exatamente "o que você fez naquele dia".
    """
    s = drg.parse_save(str(save_path), enemy_names=names)

    # DEDUP: se a última foto tem os mesmos kills e tempo, não grava lixo repetido.
    ultimo = conn.execute(
        "SELECT id, total_kills, playtime_seconds, taken_at "
        "FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if ultimo and not forcar:
        mesmo_kills = ultimo[1] == s["total_kills"]
        mesmo_tempo = abs((ultimo[2] or 0) - (s["playtime_seconds"] or 0)) < 1
        if mesmo_kills and mesmo_tempo:
            return None

    # Sempre use consultas PARAMETRIZADAS (os '?'). Nunca monte SQL com f-string.
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    valores = (agora, save_path.name, s["level"], s["credits"], s["perk_points"],
               s["games_played"], s["missions_completed"], s["times_retired"],
               s["playtime_seconds"], s["total_kills"])

    hoje = datetime.now().astimezone().date()
    if ultimo and _data_local(ultimo[3]) == hoje:
        # já existe a foto de HOJE -> atualiza ela (e troca os kills dela)
        snap_id = ultimo[0]
        conn.execute(
            """UPDATE snapshots SET
                 taken_at=?, save_file=?, level=?, credits=?, perk_points=?,
                 games_played=?, missions_completed=?, times_retired=?,
                 playtime_seconds=?, total_kills=?
               WHERE id=?""",
            (*valores, snap_id),
        )
        conn.execute("DELETE FROM kills WHERE snapshot_id=?", (snap_id,))
    else:
        # primeiro registro do dia (ou banco vazio) -> foto nova
        cur = conn.execute(
            """INSERT INTO snapshots
               (taken_at, save_file, level, credits, perk_points,
                games_played, missions_completed, times_retired, playtime_seconds, total_kills)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            valores,
        )
        snap_id = cur.lastrowid

    linhas = [(snap_id, guid, names.get(guid), count)
              for guid, count in s["kills_by_guid"].items()]
    conn.executemany(
        "INSERT INTO kills (snapshot_id, guid, name, count) VALUES (?,?,?,?)",
        linhas,
    )
    conn.commit()          # tudo junto: ou grava snapshot + kills, ou nada
    return snap_id


def mostrar_deltas(conn: sqlite3.Connection):
    """Mostra o que mais cresceu desde a foto anterior — o objetivo do histórico.

    Repare: o 'quanto cresceu' é CALCULADO na hora, com um JOIN entre as duas
    últimas fotos. A gente não guarda o delta no banco; guarda os fatos (contagens)
    e deriva o resto na consulta.
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