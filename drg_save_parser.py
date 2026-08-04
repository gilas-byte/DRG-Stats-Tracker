"""
drg_save_parser.py
==================
Deep Rock Galactic save reader (.sav file / Unreal Engine's GVAS format).

Extracts, with no external dependencies (stdlib only), data such as:
  - EnemiesKilled  -> how many of each species you killed (map GUID -> int)
  - OwnedResources -> resources you own                   (map GUID -> float)
  - Loose scalars: Credits, Level, PerkPoints, playtime, etc.

--------------------------------------------------------------------------------
HOW THE SAVE IS ORGANIZED (the "why" behind the code)
--------------------------------------------------------------------------------
The file starts with the magic b"GVAS". Then comes a sequence of PROPERTIES.
Each property has, in order:

    [FString Name] [FString Type] [int64 Size] [data...]

An FString is a string with its length up front:
    [int32 length_including_the_\0] [ascii bytes...] [\0]

A MapProperty (dictionary) has, after the header above:
    [FString KeyType] [FString ValueType]
    [1 flag byte] [int32 keys_to_remove=0] [int32 num_entries]
    and then, for each entry: [key][value]

In DRG the keys are STRUCTs of type Guid = 16 raw bytes (a unique ID of the enemy
or resource). That's why the output comes keyed by GUID, not by a readable name —
the name lives in the game's files, not in the save.

Everything is little-endian (least significant byte first).
--------------------------------------------------------------------------------
"""

import struct
import json
import sys
from pathlib import Path


# ------------------------------------------------------------------ base reading
def read_fstring(data: bytes, pos: int):
    """Read an Unreal FString. Returns (text, new_position)."""
    length = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    if length == 0:
        return "", pos
    if length > 0:                                   # ascii, null-terminated
        s = data[pos:pos + length - 1].decode("ascii", errors="replace")
        return s, pos + length
    n = -length                                      # negative length = UTF-16
    s = data[pos:pos + n * 2 - 2].decode("utf-16-le", errors="replace")
    return s, pos + n * 2


def find_property_encoded(name: str) -> bytes:
    """Return the exact bytes of an FString-name: [int32 length][ascii][\\0]."""
    return struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"


def find_property(data: bytes, name: str) -> int:
    """
    Find the EXACT offset of a property by name.

    Critical detail: you can't use data.find(b"Level") directly, because "Level"
    appears inside "LevelUpNotification", "RetiredCharacterLevels", etc. We search
    for the full FString encoding: [int32 length]["Level"]["\0"]. That way we only
    match a real property, never a piece of another one.
    """
    return data.find(find_property_encoded(name))


# ------------------------------------------------------------------ scalars
def read_scalar(data: bytes, name: str):
    """Read a simple scalar property (Int/Float/Bool). Returns (type, value)."""
    i = find_property(data, name)
    if i < 0:
        return ("NOT_FOUND", None)
    pos = i
    _, pos = read_fstring(data, pos)                 # name
    ptype, pos = read_fstring(data, pos)             # type
    _size = struct.unpack_from("<q", data, pos)[0]   # int64 value size
    pos += 8
    guid_flag = data[pos]                            # 1 byte
    pos += 1
    if ptype == "IntProperty":
        return (ptype, struct.unpack_from("<i", data, pos)[0])
    if ptype == "FloatProperty":
        return (ptype, struct.unpack_from("<f", data, pos)[0])
    if ptype == "BoolProperty":                      # bool stores the value in the flag
        return (ptype, bool(guid_flag))
    return (ptype, None)


# ------------------------------------------------------------------ GUID->value maps
def parse_guid_map(data: bytes, name: str):
    """
    Read a MapProperty whose key is a Guid (16 bytes) and value is Int or Float.
    Works for both EnemiesKilled and OwnedResources.
    Returns: dict { guid_hex(str): value(int|float) }.
    """
    i = find_property(data, name)
    if i < 0:
        return {}
    pos = i
    _, pos = read_fstring(data, pos)                 # name
    _, pos = read_fstring(data, pos)                 # "MapProperty"
    _payload = struct.unpack_from("<q", data, pos)[0]
    pos += 8
    _key_type, pos = read_fstring(data, pos)         # "StructProperty"
    val_type, pos = read_fstring(data, pos)          # "IntProperty" / "FloatProperty"
    pos += 1                                          # 1 flag byte
    _num_remove = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    num_entries = struct.unpack_from("<i", data, pos)[0]
    pos += 4

    out = {}
    for _ in range(num_entries):
        guid = data[pos:pos + 16].hex()
        pos += 16
        if val_type == "FloatProperty":
            v = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        elif val_type == "IntProperty":
            v = struct.unpack_from("<i", data, pos)[0]
            pos += 4
        else:                                         # unexpected type: bail out safely
            break
        out[guid] = v
    return out


# ------------------------------------------------------------------ GUID arrays
def parse_guid_array(data: bytes, name: str) -> list:
    """
    Read an ArrayProperty whose elements are StructProperty of type Guid (16 raw
    bytes each) and return the list of GUIDs in UPPERCASE hex.

    Works for `ForgedSchematics` (overclocks + cosmetics you forged) and for
    `UnLockedVanityItemIDs` (unlocked cosmetics). Uppercase hex matches the keys of
    `guids.json` directly.

    Layout: after the array header comes ONE struct header (field name,
    "StructProperty", size, "Guid", 16+1 bytes) and ONLY THEN the GUIDs, one after
    another. That's why the `pos += 17` before the loop (16 for the type-GUID + 1 flag).
    """
    i = find_property(data, name)
    if i < 0:
        return []
    pos = i
    _, pos = read_fstring(data, pos)                 # name
    _, pos = read_fstring(data, pos)                 # "ArrayProperty"
    pos += 8                                          # int64 payload size
    _, pos = read_fstring(data, pos)                 # inner type ("StructProperty")
    pos += 1                                          # 1 flag byte
    count = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    _, pos = read_fstring(data, pos)                 # field name (e.g. "ForgedSchematics")
    _, pos = read_fstring(data, pos)                 # "StructProperty"
    pos += 8                                          # int64 size
    _, pos = read_fstring(data, pos)                 # "Guid"
    pos += 17                                         # 16 bytes (type GUID) + 1 flag
    out = []
    for _ in range(count):
        out.append(data[pos:pos + 16].hex().upper())
        pos += 16
    return out


# ------------------------------------------------------------------ known names
# GUID -> name map. Starts almost empty on purpose: the names are NOT in the save,
# so we fill it empirically (see README / the bestiary method). The only confirmed
# one so far is the Grunt, matched against a game screenshot.
KNOWN_ENEMIES = {
    "e977bf0a42a9ed46a0d89c8d874adcff": "Glyphid Grunt",  # confirmed (75,466)
    # "481284770880ff4d........": "Glyphid Swarmer(?)",   # to be confirmed
    # fill the rest by reading the bestiary and matching by kill count
}


# ------------------------------------------------------------------ classes/rank
# Canonical GUIDs of the 4 playable classes. They are fixed DRG constants (the same
# in any save). In the file, each class is a "block" keyed by this GUID.
CLASS_GUIDS = {
    "9edd56f1eebcc5488d5b5e5b80b62db4": "Driller",
    "85ef626c65f1024a8dfeb5d0f3909d2e": "Engineer",
    "ae56e180fec0c44d96fa29c28366b97b": "Gunner",
    "30d8ea17d8fbba4c95306de9655c2f8c": "Scout",
}

# Cumulative XP needed to REACH each level (index 0 = level 1, ... index 24 =
# level 25). A class's level is DERIVED from XP: it isn't stored. On reaching 315000
# (level 25) the XP caps and unlocks the promotion. Source: official DRG wiki.
CLASS_XP_TABLE = [
    0, 3000, 7000, 12000, 18000, 25000, 33000, 42000, 52000, 63000,
    75000, 88000, 102000, 117000, 132500, 148500, 165000, 182000, 199500,
    217500, 236000, 255000, 274500, 294500, 315000,
]


# ------------------------------------------------------------------ mission stats
# The game shows "Missions Completed" (e.g. 445) on a stats screen, but that number
# is NOT `NumberOfGamesPlayed` (which counts EVERY game started, including aborted/
# failed ones — 504 in the test). "Completed" lives inside a `MissionStatsSave`
# block -> array `Counters`, where each entry has 3 fields in order:
#     PlayerClassID (Guid 16b)  ->  MissionStatID (Guid 16b)  ->  Value (FloatProperty)
# So each statistic is stored PER CLASS. The displayed total is the SUM of the 4
# classes for the same MissionStatID. Confirmed GUID (sum = 445, matching the print):
MISSIONS_COMPLETED_STAT = "8ae243468b5da06e7bd0e4c806000000"


def parse_mission_stat(data: bytes, stat_guid: str) -> int:
    """
    Sum the Value of a MissionStatID across all classes and return the total (int).

    Strategy: instead of decoding the whole `Counters` array (struct inside struct),
    we scan each entry by anchoring on "MissionStatID". For each one:
      - the stat's Guid is the 16 bytes right BEFORE the FString "Value";
      - the number is the FloatProperty right AFTER (int64 size + 1 flag byte + float).
    If the Guid matches the target, sum. Returns 0 if the block doesn't exist.
    """
    alvo = bytes.fromhex(stat_guid)
    total = 0.0
    achou = False
    pos = 0
    marca = b"MissionStatID"
    while True:
        i = data.find(marca, pos)
        if i < 0:
            break
        pos = i + len(marca)
        v = data.find(b"Value\x00", pos)             # start of the Value field
        if v < 0:
            break
        if data[v - 16:v] == alvo:                   # the 16 bytes before = the stat's Guid
            f = data.find(b"FloatProperty\x00", v)
            off = f + len(b"FloatProperty\x00")
            # FloatProperty: [int64 size][1 flag byte][float32]
            total += struct.unpack_from("<f", data, off + 8 + 1)[0]
            achou = True
    return round(total) if achou else 0


def parse_mission_stats(data: bytes) -> dict:
    """
    Sum EVERY MissionStat's Value across the 4 classes -> {guid_hex: int}.

    Generalizes parse_mission_stat to pull ALL stats at once. We anchor on the
    "Value" FString of each Counters entry; the stat's 16-byte Guid is the bytes
    ending 4 bytes BEFORE it -- the trailing 4 bytes are the int32 length prefix of
    "Value" (=6), NOT part of the Guid. (Reverse-engineered from the game's
    /Game/GameElements/KPI/MissionStats/MS_* assets; see mission_stats.json.)
    We bound the FloatProperty lookup to a few bytes so unrelated "Value" strings
    elsewhere in the save can't produce bogus entries.
    """
    tot: dict[str, float] = {}
    pos = 0
    while True:
        v = data.find(b"Value\x00", pos)
        if v < 0:
            break
        pos = v + 1
        f = data.find(b"FloatProperty\x00", v, v + 40)   # must be a stat entry
        if f < 0 or v < 20:
            continue
        guid = data[v - 20:v - 4].hex()                  # 16-byte Guid (see docstring)
        off = f + len(b"FloatProperty\x00")
        tot[guid] = tot.get(guid, 0.0) + struct.unpack_from("<f", data, off + 8 + 1)[0]
    return {g: round(x) for g, x in tot.items()}


def level_from_xp(xp: int) -> int:
    """Convert a class's accumulated XP into the matching level 1..25."""
    lvl = 1
    for i, limite in enumerate(CLASS_XP_TABLE):
        if xp >= limite:
            lvl = i + 1
        else:
            break
    return lvl


def _read_int_at(data: bytes, name_off: int) -> int:
    """Read the value of an IntProperty whose NAME starts at name_off."""
    pos = name_off
    _, pos = read_fstring(data, pos)                  # name
    _, pos = read_fstring(data, pos)                  # type ("IntProperty")
    pos += 8                                           # int64 size
    pos += 1                                           # 1 flag byte
    return struct.unpack_from("<i", data, pos)[0]


def parse_classes(data: bytes) -> list[dict]:
    """
    Read the progression blocks of the 4 classes (Driller/Engineer/Gunner/Scout).

    In the save, each block starts with the class GUID (16 raw bytes) followed by the
    progression struct, whose first properties are:
        XP (IntProperty) -> TimesRetired (IntProperty) -> RetiredCharacterLevels

    Important DRG vocabulary detail: **"TimesRetired" per class is the number of
    PROMOTIONS of that class** (the engine calls a promotion "retire"). Not to be
    confused with the whole account's retirement/legacy.

    Returns a list of dicts: name, guid, xp, level, promotions, retired_levels.
    """
    enc_xp = struct.pack("<i", 3) + b"XP\x00"          # FString "XP"
    enc_tr = find_property_encoded("TimesRetired")
    enc_rl = find_property_encoded("RetiredCharacterLevels")

    out = []
    i = 0
    while True:
        j = data.find(enc_xp, i)
        if j < 0:
            break
        i = j + 1

        # It's only a class block if a "TimesRetired" shows up right after the XP.
        tr = data.find(enc_tr, j)
        if not (0 < tr - j < 120):
            continue

        guid = data[j - 16:j].hex()                    # the GUID keys the block
        name = CLASS_GUIDS.get(guid)
        if not name:
            continue                                   # ignore the ghost GUID

        xp = _read_int_at(data, j)
        promotions = _read_int_at(data, tr)
        rl_off = data.find(enc_rl, tr)
        retired_levels = _read_int_at(data, rl_off) if 0 < rl_off - tr < 120 else 0

        out.append({
            "name": name,
            "guid": guid,
            "xp": xp,
            "level": level_from_xp(xp),
            "promotions": promotions,
            "retired_levels": retired_levels,
        })

    # fixed, friendly display order
    ordem = ["Driller", "Engineer", "Gunner", "Scout"]
    out.sort(key=lambda c: ordem.index(c["name"]) if c["name"] in ordem else 99)
    return out


# ------------------------------------------------------------------ main API
def parse_save(path: str, enemy_names: dict | None = None) -> dict:
    """Read the whole save and return a dict with everything that matters."""
    data = Path(path).read_bytes()
    if data[:4] != b"GVAS":
        raise ValueError("Não parece um save GVAS válido (magic 'GVAS' ausente).")

    names = enemy_names or KNOWN_ENEMIES

    kills_by_guid = parse_guid_map(data, "EnemiesKilled")
    kills_named = {
        names.get(g, f"UNKNOWN_{g[:12]}"): v
        for g, v in kills_by_guid.items()
    }

    # --- Account rank and promotions: DERIVED from the 4 class blocks ---
    # The rank (the big in-game number, e.g. 115) is NOT stored. DRG computes it:
    #   rank = (sum of the total levels of all classes) // 3
    # where a class's "total level" = already-promoted levels (RetiredCharacterLevels)
    # + current level. Account promotions = sum of TimesRetired per class.
    classes = parse_classes(data)
    promotions_total = sum(c["promotions"] for c in classes)
    total_levels = sum(c["retired_levels"] + c["level"] for c in classes)
    player_rank = total_levels // 3 if classes else None

    return {
        "level":            player_rank,             # account rank (e.g. 115)
        "player_rank":      player_rank,             # explicit alias
        "promotions":       promotions_total,        # total promotions (e.g. 10)
        "classes":          classes,                 # per-class detail (dashboard)
        "credits":          read_scalar(data, "Credits")[1],
        "perk_points":      read_scalar(data, "PerkPoints")[1],
        "games_played":     read_scalar(data, "NumberOfGamesPlayed")[1],
        "missions_completed": parse_mission_stat(data, MISSIONS_COMPLETED_STAT),
        "times_retired":    promotions_total,        # name kept for db schema compat.
        "playtime_seconds": read_scalar(data, "TotalPlayTimeSeconds")[1],
        "total_kills":      sum(kills_by_guid.values()),
        "species_count":    len(kills_by_guid),
        "kills_by_guid":    kills_by_guid,           # raw, for the db/ETL
        "kills_named":      kills_named,             # readable, for display
        "resources_by_guid": parse_guid_map(data, "OwnedResources"),
        "forged_schematics": parse_guid_array(data, "ForgedSchematics"),      # overclocks + forged cosmetics
        "vanity_items":      parse_guid_array(data, "UnLockedVanityItemIDs"),  # unlocked cosmetics
    }


# ------------------------------------------------------------------ CLI
def _main():
    if len(sys.argv) < 2:
        print("uso: python drg_save_parser.py <caminho_do_.sav> [mapa_nomes.json]")
        sys.exit(1)

    names = None
    if len(sys.argv) >= 3:
        names = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    s = parse_save(sys.argv[1], enemy_names=names)

    print("=" * 48)
    print("  DEEP ROCK GALACTIC — resumo do save")
    print("=" * 48)
    print(f"  Rank da conta ..... {s['player_rank']}")
    print(f"  Créditos .......... {s['credits']:,}")
    print(f"  Perk points ....... {s['perk_points']}")
    print(f"  Missões concluídas  {s['missions_completed']}")
    print(f"  Partidas jogadas .. {s['games_played']}")
    print(f"  Promoções (total) . {s['promotions']}")
    for c in s["classes"]:
        estrelas = "*" * c["promotions"]
        print(f"     - {c['name']:<9} lvl {c['level']:<2} "
              f"({c['promotions']} promo {estrelas})")
    hrs = (s['playtime_seconds'] or 0) / 3600
    print(f"  Tempo de jogo ..... {hrs:,.1f} h")
    print(f"  Total de kills .... {s['total_kills']:,}")
    print(f"  Espécies mortas ... {s['species_count']}")
    print("-" * 48)
    print("  Top 15 por kills:")
    ranked = sorted(s["kills_named"].items(), key=lambda kv: -kv[1])
    for i, (nome, v) in enumerate(ranked[:15], 1):
        print(f"   {i:>2}. {nome:<28} {v:>8,}")


if __name__ == "__main__":
    _main()
