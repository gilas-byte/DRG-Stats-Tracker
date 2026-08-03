"""
drg_save_parser.py
==================
Leitor de save do Deep Rock Galactic (arquivo .sav / formato GVAS da Unreal Engine).

Extrai, sem nenhuma dependência externa (só stdlib), dados como:
  - EnemiesKilled  -> quantos inimigos de cada espécie você matou (mapa GUID -> int)
  - OwnedResources -> recursos que você possui             (mapa GUID -> float)
  - Escalares soltos: Credits, Level, PerkPoints, tempo de jogo, etc.

--------------------------------------------------------------------------------
COMO O SAVE É ORGANIZADO (o "porquê" por trás do código)
--------------------------------------------------------------------------------
O arquivo começa com a "magic" b"GVAS". Depois vem uma sequência de PROPRIEDADES.
Cada propriedade tem, em ordem:

    [FString Nome] [FString Tipo] [int64 Tamanho] [dados...]

Uma FString é uma string com o tamanho na frente:
    [int32 tamanho_incluindo_o_\0] [bytes ascii...] [\0]

Um MapProperty (dicionário) tem, depois do cabeçalho acima:
    [FString TipoDaChave] [FString TipoDoValor]
    [1 byte flag] [int32 chaves_a_remover=0] [int32 num_entradas]
    e então, para cada entrada: [chave][valor]

No DRG as chaves são STRUCTs do tipo Guid = 16 bytes crus (um ID único do inimigo
ou recurso). Por isso a saída vem por GUID, não por nome legível — o nome mora nos
arquivos do jogo, não no save.

Tudo é little-endian (byte menos significativo primeiro).
--------------------------------------------------------------------------------
"""

import struct
import json
import sys
from pathlib import Path


# ------------------------------------------------------------------ leitura base
def read_fstring(data: bytes, pos: int):
    """Lê uma FString da Unreal. Retorna (texto, nova_posicao)."""
    length = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    if length == 0:
        return "", pos
    if length > 0:                                   # ascii, terminada em \0
        s = data[pos:pos + length - 1].decode("ascii", errors="replace")
        return s, pos + length
    n = -length                                      # length negativo = UTF-16
    s = data[pos:pos + n * 2 - 2].decode("utf-16-le", errors="replace")
    return s, pos + n * 2


def find_property_encoded(name: str) -> bytes:
    """Devolve os bytes exatos de uma FString-nome: [int32 tamanho][ascii][\\0]."""
    return struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"


def find_property(data: bytes, name: str) -> int:
    """
    Acha o offset EXATO de uma propriedade pelo nome.

    Detalhe crítico: não dá pra usar data.find(b"Level") direto, porque "Level"
    aparece dentro de "LevelUpNotification", "RetiredCharacterLevels", etc.
    A gente busca a codificação FString completa: [int32 tamanho]["Level"]["\0"].
    Assim só casamos com uma propriedade de verdade, nunca com um pedaço de outra.
    """
    return data.find(find_property_encoded(name))


# ------------------------------------------------------------------ escalares
def read_scalar(data: bytes, name: str):
    """Lê uma propriedade escalar simples (Int/Float/Bool). Retorna (tipo, valor)."""
    i = find_property(data, name)
    if i < 0:
        return ("NOT_FOUND", None)
    pos = i
    _, pos = read_fstring(data, pos)                 # nome
    ptype, pos = read_fstring(data, pos)             # tipo
    _size = struct.unpack_from("<q", data, pos)[0]   # int64 tamanho do valor
    pos += 8
    guid_flag = data[pos]                            # 1 byte
    pos += 1
    if ptype == "IntProperty":
        return (ptype, struct.unpack_from("<i", data, pos)[0])
    if ptype == "FloatProperty":
        return (ptype, struct.unpack_from("<f", data, pos)[0])
    if ptype == "BoolProperty":                      # bool guarda o valor no flag
        return (ptype, bool(guid_flag))
    return (ptype, None)


# ------------------------------------------------------------------ mapas GUID->valor
def parse_guid_map(data: bytes, name: str):
    """
    Lê um MapProperty cuja chave é um Guid (16 bytes) e o valor é Int ou Float.
    Serve tanto pra EnemiesKilled quanto pra OwnedResources.
    Retorna: dict { guid_hex(str): valor(int|float) }.
    """
    i = find_property(data, name)
    if i < 0:
        return {}
    pos = i
    _, pos = read_fstring(data, pos)                 # nome
    _, pos = read_fstring(data, pos)                 # "MapProperty"
    _payload = struct.unpack_from("<q", data, pos)[0]
    pos += 8
    _key_type, pos = read_fstring(data, pos)         # "StructProperty"
    val_type, pos = read_fstring(data, pos)          # "IntProperty" / "FloatProperty"
    pos += 1                                          # 1 byte flag
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
        else:                                         # tipo inesperado: aborta seguro
            break
        out[guid] = v
    return out


# ------------------------------------------------------------------ arrays de GUID
def parse_guid_array(data: bytes, name: str) -> list:
    """
    Lê um ArrayProperty cujos elementos são StructProperty do tipo Guid (16 bytes
    crus cada) e devolve a lista dos GUIDs em hex MAIÚSCULO.

    Serve pra `ForgedSchematics` (overclocks + cosméticos que você forjou) e pra
    `UnLockedVanityItemIDs` (cosméticos desbloqueados). O hex maiúsculo casa direto
    com as chaves do `guids.json`.

    Layout: depois do cabeçalho do array vem UM cabeçalho de struct (nome do campo,
    "StructProperty", tamanho, "Guid", 16+1 bytes) e SÓ ENTÃO os GUIDs, um atrás do
    outro. Por isso o `pos += 17` antes do laço (16 do GUID-do-tipo + 1 de flag).
    """
    i = find_property(data, name)
    if i < 0:
        return []
    pos = i
    _, pos = read_fstring(data, pos)                 # nome
    _, pos = read_fstring(data, pos)                 # "ArrayProperty"
    pos += 8                                          # int64 tamanho do payload
    _, pos = read_fstring(data, pos)                 # tipo interno ("StructProperty")
    pos += 1                                          # 1 byte flag
    count = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    _, pos = read_fstring(data, pos)                 # nome do campo (ex.: "ForgedSchematics")
    _, pos = read_fstring(data, pos)                 # "StructProperty"
    pos += 8                                          # int64 tamanho
    _, pos = read_fstring(data, pos)                 # "Guid"
    pos += 17                                         # 16 bytes (GUID do tipo) + 1 flag
    out = []
    for _ in range(count):
        out.append(data[pos:pos + 16].hex().upper())
        pos += 16
    return out


# ------------------------------------------------------------------ nomes conhecidos
# Mapa GUID -> nome. Começa quase vazio de propósito: os nomes NÃO estão no save,
# então a gente preenche empiricamente (ver README / método do bestiário).
# O único confirmado até agora é o Grunt, batido com a screenshot do jogo.
KNOWN_ENEMIES = {
    "e977bf0a42a9ed46a0d89c8d874adcff": "Glyphid Grunt",  # confirmado (75.466)
    # "481284770880ff4d........": "Glyphid Swarmer(?)",   # a confirmar
    # preencher o resto lendo o bestiário e casando pelo número de kills
}


# ------------------------------------------------------------------ classes/rank
# GUIDs canônicos das 4 classes jogáveis. São constantes fixas do DRG (iguais em
# qualquer save). No arquivo, cada classe é um "bloco" chaveado por esse GUID.
CLASS_GUIDS = {
    "9edd56f1eebcc5488d5b5e5b80b62db4": "Driller",
    "85ef626c65f1024a8dfeb5d0f3909d2e": "Engineer",
    "ae56e180fec0c44d96fa29c28366b97b": "Gunner",
    "30d8ea17d8fbba4c95306de9655c2f8c": "Scout",
}

# XP cumulativo necessário pra ATINGIR cada level (índice 0 = level 1, ... índice
# 24 = level 25). O level de uma classe é DERIVADO do XP: não fica salvo. Ao chegar
# em 315000 (level 25) o XP trava e libera a promoção. Fonte: wiki oficial do DRG.
CLASS_XP_TABLE = [
    0, 3000, 7000, 12000, 18000, 25000, 33000, 42000, 52000, 63000,
    75000, 88000, 102000, 117000, 132500, 148500, 165000, 182000, 199500,
    217500, 236000, 255000, 274500, 294500, 315000,
]


# ------------------------------------------------------------------ mission stats
# O jogo mostra "Missions Completed" (ex.: 445) numa tela de estatísticas, mas esse
# número NÃO é o `NumberOfGamesPlayed` (que conta TODA partida iniciada, inclusive as
# abandonadas/falhadas — no teste deu 504). O "concluídas" mora dentro de um bloco
# `MissionStatsSave` → array `Counters`, onde cada entrada tem 3 campos em ordem:
#     PlayerClassID (Guid 16b)  →  MissionStatID (Guid 16b)  →  Value (FloatProperty)
# Ou seja: cada estatística é guardada POR CLASSE. O total exibido é a SOMA das 4
# classes de um mesmo MissionStatID. GUID confirmado (soma = 445, batendo com o print):
MISSIONS_COMPLETED_STAT = "8ae243468b5da06e7bd0e4c806000000"


def parse_mission_stat(data: bytes, stat_guid: str) -> int:
    """
    Soma o Value de um MissionStatID entre todas as classes e devolve o total (int).

    Estratégia: em vez de decodificar o array `Counters` inteiro (struct dentro de
    struct), a gente varre cada entrada pela âncora "MissionStatID". Pra cada uma:
      - o Guid do stat são os 16 bytes logo ANTES da FString "Value";
      - o número é o FloatProperty logo DEPOIS (int64 tamanho + 1 byte flag + float).
    Se o Guid casa com o alvo, soma. Retorna 0 se o bloco não existir.
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
        v = data.find(b"Value\x00", pos)             # início do campo Value
        if v < 0:
            break
        if data[v - 16:v] == alvo:                   # os 16 bytes antes = Guid do stat
            f = data.find(b"FloatProperty\x00", v)
            off = f + len(b"FloatProperty\x00")
            # FloatProperty: [int64 tamanho][1 byte flag][float32]
            total += struct.unpack_from("<f", data, off + 8 + 1)[0]
            achou = True
    return round(total) if achou else 0


def level_from_xp(xp: int) -> int:
    """Converte o XP acumulado de uma classe no level 1..25 correspondente."""
    lvl = 1
    for i, limite in enumerate(CLASS_XP_TABLE):
        if xp >= limite:
            lvl = i + 1
        else:
            break
    return lvl


def _read_int_at(data: bytes, name_off: int) -> int:
    """Lê o valor de uma IntProperty cujo NOME começa em name_off."""
    pos = name_off
    _, pos = read_fstring(data, pos)                  # nome
    _, pos = read_fstring(data, pos)                  # tipo ("IntProperty")
    pos += 8                                           # int64 tamanho
    pos += 1                                           # 1 byte flag
    return struct.unpack_from("<i", data, pos)[0]


def parse_classes(data: bytes) -> list[dict]:
    """
    Lê os blocos de progresso das 4 classes (Driller/Engineer/Gunner/Scout).

    No save, cada bloco começa com o GUID da classe (16 bytes crus) seguido da
    struct de progresso, cujas primeiras propriedades são:
        XP (IntProperty) -> TimesRetired (IntProperty) -> RetiredCharacterLevels

    Detalhe importante do vocabulário do DRG: **"TimesRetired" por classe é o
    número de PROMOÇÕES daquela classe** (a engine chama promoção de "retire").
    Não confundir com a aposentadoria/legacy da conta inteira.

    Retorna uma lista de dicts: name, guid, xp, level, promotions, retired_levels.
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

        # Só é bloco de classe se um "TimesRetired" aparece logo depois do XP.
        tr = data.find(enc_tr, j)
        if not (0 < tr - j < 120):
            continue

        guid = data[j - 16:j].hex()                    # o GUID chaveia o bloco
        name = CLASS_GUIDS.get(guid)
        if not name:
            continue                                   # ignora o GUID fantasma

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

    # ordem fixa e amigável pra exibição
    ordem = ["Driller", "Engineer", "Gunner", "Scout"]
    out.sort(key=lambda c: ordem.index(c["name"]) if c["name"] in ordem else 99)
    return out


# ------------------------------------------------------------------ API principal
def parse_save(path: str, enemy_names: dict | None = None) -> dict:
    """Lê o save inteiro e devolve um dicionário com tudo que interessa."""
    data = Path(path).read_bytes()
    if data[:4] != b"GVAS":
        raise ValueError("Não parece um save GVAS válido (magic 'GVAS' ausente).")

    names = enemy_names or KNOWN_ENEMIES

    kills_by_guid = parse_guid_map(data, "EnemiesKilled")
    kills_named = {
        names.get(g, f"UNKNOWN_{g[:12]}"): v
        for g, v in kills_by_guid.items()
    }

    # --- Rank da conta e promoções: DERIVADOS dos 4 blocos de classe ---
    # O rank (o número grande no jogo, ex.: 115) NÃO fica salvo. O DRG calcula:
    #   rank = (soma dos levels totais de todas as classes) // 3
    # onde "level total" de uma classe = níveis já promovidos (RetiredCharacterLevels)
    # + level atual. Promoções da conta = soma dos TimesRetired por classe.
    classes = parse_classes(data)
    promotions_total = sum(c["promotions"] for c in classes)
    total_levels = sum(c["retired_levels"] + c["level"] for c in classes)
    player_rank = total_levels // 3 if classes else None

    return {
        "level":            player_rank,             # rank da conta (ex.: 115)
        "player_rank":      player_rank,             # apelido explícito
        "promotions":       promotions_total,        # total de promoções (ex.: 10)
        "classes":          classes,                 # detalhe por classe (dashboard)
        "credits":          read_scalar(data, "Credits")[1],
        "perk_points":      read_scalar(data, "PerkPoints")[1],
        "games_played":     read_scalar(data, "NumberOfGamesPlayed")[1],
        "missions_completed": parse_mission_stat(data, MISSIONS_COMPLETED_STAT),
        "times_retired":    promotions_total,        # nome mantido p/ compat. do banco
        "playtime_seconds": read_scalar(data, "TotalPlayTimeSeconds")[1],
        "total_kills":      sum(kills_by_guid.values()),
        "species_count":    len(kills_by_guid),
        "kills_by_guid":    kills_by_guid,           # cru, pra o banco/ETL
        "kills_named":      kills_named,             # legível, pra exibir
        "resources_by_guid": parse_guid_map(data, "OwnedResources"),
        "forged_schematics": parse_guid_array(data, "ForgedSchematics"),      # overclocks + cosm. forjados
        "vanity_items":      parse_guid_array(data, "UnLockedVanityItemIDs"),  # cosméticos desbloqueados
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