#!/usr/bin/env python3
"""
extract_mission_stats.py — how mission_stats.json was reverse-engineered.

The save stores each statistic keyed by a 16-byte GUID (a MissionStatID), but NOT
the human name. This tool recovers GUID -> name by reading the game's own pak:

    1. Find FSD-WindowsNoEditor.pak (UE4 pak v11, Zlib-compressed) in any Steam library.
    2. Parse the pak index (mount point + full directory index + encoded entries) to
       locate every /Game/GameElements/KPI/MissionStats/MS_* asset.
    3. Decompress each tiny asset (single Zlib block) and scan it for a 16-byte value
       that ALSO appears in your save's stat GUIDs -> that's the stat's GUID.
    4. Attach a curated category + display label (the wording the game shows) and
       write mission_stats.json.

Key gotcha we learned: in the save, the stat's true 16-byte GUID ends 4 bytes BEFORE
the "Value" FString -- the trailing 4 bytes are the int32 length prefix (=6) of the
word "Value", NOT part of the GUID. Anchoring on the wrong 16 bytes made every GUID
look like it ended in `06000000`.

Run from the project folder (needs snapshot.py + a readable save):  python tools/extract_mission_stats.py
Only needs Python stdlib. Re-run to regenerate mission_stats.json from scratch.
"""
import struct
import zlib
import re
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import snapshot   # reuse find_save + _steam_libraries

PREFIX = "FSD/Content/GameElements/KPI/MissionStats/"


def find_pak() -> Path | None:
    """Locate FSD-WindowsNoEditor.pak across every Steam library on this PC."""
    for lib in snapshot._steam_libraries():
        p = Path(lib) / "steamapps" / "common" / "Deep Rock Galactic" / "FSD" / "Content" / "Paks" / "FSD-WindowsNoEditor.pak"
        if p.exists():
            return p
    return None


def _fstring(b, p):
    n = struct.unpack_from("<i", b, p)[0]; p += 4
    if n == 0:
        return "", p
    if n > 0:
        return b[p:p + n - 1].decode("latin1"), p + n
    n = -n
    return b[p:p + 2 * n - 2].decode("utf-16-le"), p + 2 * n


def read_pak_files(f):
    """Return (files: {path: encoded_entry_offset}, encoded_blob)."""
    f.seek(0, 2); size = f.tell()
    f.seek(size - 256); foot = f.read(256)
    mi = foot.rfind(bytes.fromhex("e1126f5a"))          # pak magic 0x5A6F12E1
    index_off, index_size = struct.unpack_from("<qq", foot, mi + 8)

    f.seek(index_off); idx = f.read(index_size); p = 0
    _, p = _fstring(idx, p); p += 12                     # mount, NumEntries(4)+PathHashSeed(8)
    if struct.unpack_from("<i", idx, p)[0]:              # has path-hash index
        p += 4 + 36
    else:
        p += 4
    p += 4                                               # has full-directory index (assume yes)
    fdi_off, fdi_size = struct.unpack_from("<qq", idx, p); p += 16 + 20
    enc_size = struct.unpack_from("<i", idx, p)[0]; p += 4
    encoded = idx[p:p + enc_size]

    f.seek(fdi_off); fdi = f.read(fdi_size); p = 0
    ndirs = struct.unpack_from("<i", fdi, p)[0]; p += 4
    files = {}
    for _ in range(ndirs):
        dname, p = _fstring(fdi, p)
        nf = struct.unpack_from("<i", fdi, p)[0]; p += 4
        for _ in range(nf):
            fname, p = _fstring(fdi, p)
            eoff = struct.unpack_from("<i", fdi, p)[0]; p += 4
            files[dname + fname] = eoff
    return files, encoded


def entry_loc(encoded, eoff):
    """Decode an encoded pak entry down to (data offset, compressed size, method idx)."""
    q = eoff
    v0 = struct.unpack_from("<I", encoded, q)[0]; q += 4
    off = struct.unpack_from("<I", encoded, q)[0] if v0 & 0x80000000 else struct.unpack_from("<Q", encoded, q)[0]
    q += 4 if v0 & 0x80000000 else 8
    us = struct.unpack_from("<I", encoded, q)[0] if v0 & 0x40000000 else struct.unpack_from("<Q", encoded, q)[0]
    q += 4 if v0 & 0x40000000 else 8
    cmi = (v0 >> 23) & 0x3f
    if cmi:
        sz = struct.unpack_from("<I", encoded, q)[0] if v0 & 0x20000000 else struct.unpack_from("<Q", encoded, q)[0]
    else:
        sz = us
    return off, sz, cmi


def read_asset(f, files, encoded, path):
    off, sz, cmi = entry_loc(encoded, files[path])
    f.seek(off); window = f.read(sz + 1024)
    if cmi == 0:
        return window                                    # stored uncompressed
    for m in re.finditer(b"\x78[\x01\x9c\xda]", window): # find the Zlib stream
        try:
            return zlib.decompressobj().decompress(window[m.start():])
        except Exception:
            continue
    return b""


# Curated: internal asset name -> (category, display label as the game shows it).
CURATED = {
 "MS_Completed_TotalMissions": ("Overview", "Missions Completed"),
 "MS_Completed_TotalSoloMissions": ("Overview", "Solo Missions Completed"),
 "MS_Completed_SecondaryMissions": ("Overview", "Secondary Missions Completed"),
 "MS_Completed_TotalCampaignMissions": ("Overview", "Assignment Missions Completed"),
 "MS_Completed_TotalCampaigns": ("Overview", "Assignments Completed"),
 "MS_Killed_TotalEnemies": ("Overview", "Enemies Killed"),
 "MS_Mined_TotalMinerals": ("Overview", "Minerals Mined"),
 "MS_DistanceTravelled": ("Overview", "Distance Travelled"),
 "MS_TimePlayed": ("Overview", "Mission Time"),
 "MS_Death_TotalDowns": ("Overview", "Total Downs"),
 "MS_Death_TotalDownsDrunk": ("Overview", "Downs While Drunk"),
 "MS_LevelUp_Character": ("Overview", "Character Level-Ups"),
 "MS_JettyBoot_CreditsSpent": ("Economy", "Credits Spent on Jetty Boot"),
 "MS_BartenderTips": ("Economy", "Total Credits Tipped"),
 "MS_Drinkable_TotalConsumed": ("Economy", "Beverages Consumed"),
 "MS_Drinkable_TotalRoundsOrdered": ("Economy", "Beverage Rounds Ordered"),
 "MS_Drinkable_SpecialBeersUnlocked": ("Economy", "Special Beers Unlocked"),
 "MS_EquipmentUpgrades_Purchased": ("Economy", "Equipment Upgrades Purchased"),
 "MS_VanityItems_Purchased": ("Economy", "Accessory Items Purchased"),
 "MS_Cosmetic_Mastery": ("Forging", "Cosmetic Mastery Levels"),
 "MS_Crafting_Cosmetics": ("Forging", "Cosmetics Forged"),
 "MS_Crafting_WeaponSkins": ("Forging", "Weapon Skins Forged"),
 "MS_Crafting_Overclocks": ("Forging", "Weapon Overclocks Forged"),
 "MS_Crafting_Mastery": ("Forging", "Forging Mastery Levels"),
 "MS_Assignments_WeaponLicenses": ("Progression", "Weapon License Assignments"),
 "MS_Assignments_Promoted_Weekly": ("Progression", "Weekly Promotion Assignments"),
 "MS_Assignments_Unluck_Facility": ("Progression", "Facility Unlock Assignment"),
 "MS_Completed_SeasonEvents": ("Progression", "Season Events Completed"),
 "MS_Completed_SeasonChallenge": ("Progression", "Season Challenges Completed"),
 "MS_Completed_DeepDive": ("Progression", "Deep Dives Completed"),
 "MS_Completed_EliteDeepDive": ("Progression", "Elite Deep Dives Completed"),
 "MS_Completed_DeepDive_BestTime": ("Progression", "Best Deep Dive Time"),
 "MS_Completed_EliteDeepDive_BestTime": ("Progression", "Best Elite Deep Dive Time"),
 "MS_Completed_MiningExpedition": ("Mission Type", "Mining Expeditions"),
 "MS_Completed_PointExtraction": ("Mission Type", "Point Extractions"),
 "MS_Completed_EggHunts": ("Mission Type", "Egg Hunts"),
 "MS_Completed_EliminationMissions": ("Mission Type", "Eliminations"),
 "MS_Completed_EscortMissions": ("Mission Type", "Escort Duties"),
 "MS_Completed_RefineryMissions": ("Mission Type", "On-Site Refining"),
 "MS_Completed_SalvageMissions": ("Mission Type", "Salvage Operations"),
 "MS_Completed_DeepScan": ("Mission Type", "Deep Scans"),
 "MS_Completed_HeavyExtraction": ("Mission Type", "Heavy Extractions"),
 "MS_Completed_Facility": ("Mission Type", "Industrial Sabotage"),
 "MS_CoreRifts_Closed": ("Mission Type", "Core Rifts Closed"),
 "MS_Completed_AzureWeald": ("Biome", "Azure Weald"),
 "MS_Completed_Crystal": ("Biome", "Crystalline Caverns"),
 "MS_Completed_Fungus": ("Biome", "Fungus Bogs"),
 "MS_Completed_HollowBough": ("Biome", "Hollow Bough"),
 "MS_Completed_IceCaves": ("Biome", "Glacial Strata"),
 "MS_Completed_Lush": ("Biome", "Dense Biozone"),
 "MS_Completed_Magma": ("Biome", "Magma Core"),
 "MS_Completed_OssuaryDepths": ("Biome", "Ossuary Depths"),
 "MS_Completed_Radioactive": ("Biome", "Radioactive Exclusion Zone"),
 "MS_Completed_Salt": ("Biome", "Salt Pits"),
 "MS_Completed_Sandblasted": ("Biome", "Sandblasted Corridors"),
 "MS_Completed_Driller": ("Class", "Driller"),
 "MS_Completed_Engineer": ("Class", "Engineer"),
 "MS_Completed_Gunner": ("Class", "Gunner"),
 "MS_Completed_Scout": ("Class", "Scout"),
 "MS_Completed_Hazard3": ("Hazard", "Hazard 3"),
 "MS_Completed_Hazard5": ("Hazard", "Hazard 5"),
 "MS_Secondary_ApocaBloom": ("Secondary", "Apoca Bloom"),
 "MS_Secondary_BooloCaps": ("Secondary", "Boolo Cap"),
 "MS_Secondary_DestroyBhaBarnacle": ("Secondary", "Bha Barnacle"),
 "MS_Secondary_DestroyEggs": ("Secondary", "Glyphid Eggs"),
 "MS_Secondary_Dystrum": ("Secondary", "Dystrum"),
 "MS_Secondary_FindEbonut": ("Secondary", "Ebonut"),
 "MS_Secondary_FindGunkSeed": ("Secondary", "Gunk Seed"),
 "MS_Secondary_Fossils": ("Secondary", "Fossils"),
 "MS_Secondary_Holomite": ("Secondary", "Hollomite"),
 "MS_Secondary_KillFesterFleas": ("Secondary", "Fester Fleas"),
 "MS_Warnings_CaveLeechClusters": ("Warning", "Cave Leech Cluster"),
 "MS_Warnings_ExploderInfestations": ("Warning", "Exploder Infestation"),
 "MS_Warnings_MacteraPlagues": ("Warning", "Mactera Plague"),
 "MS_Warnings_NoShields": ("Warning", "Shield Disruption"),
 "MS_Warnings_Ghost": ("Warning", "Haunted Cave"),
 "MS_Warnings_InfestedEnemies": ("Warning", "Parasites"),
 "MS_Warnings_LethalEnemies": ("Warning", "Lethal Enemies"),
 "MS_Warnings_NoOxygen": ("Warning", "Low Oxygen"),
 "MS_Warnings_HeroEnemies": ("Warning", "Elite Threat"),
 "MS_Warnings_Swarmageddon": ("Warning", "Swarmageddon"),
 "MS_Warnings_Regeneration": ("Warning", "Regenerative Bugs"),
 "MS_Warnings_Plague": ("Warning", "Lithophage Outbreak"),
 "MS_Warnings_RivalIncursion": ("Warning", "Rival Presence"),
 "MS_Warnings_RockInfestation": ("Warning", "Ebonite Outbreak"),
 "MS_Warnings_BulletHell": ("Warning", "Duck and Cover"),
 "MS_Warnings_OssiranColony": ("Warning", "Pit Jaw Colony"),
 "MS_Warnings_ScrabNestingGrounds": ("Warning", "Scrab Nesting Grounds"),
 "MS_Warnings_CoreCorruption": ("Warning", "Core Corruption"),
 "MS_Warnings_DoubleWarning": ("Warning", "Double Warning"),
 "MS_BoneFragmentCollected_S06": ("Misc", "Bone Fragments (S06)"),
 "MS_PlagueHeartsCollected_S04": ("Misc", "Plague Hearts (S04)"),
 "MS_Plague_Cleaned": ("Misc", "Plague Cleaned"),
 "MS_DataCells_Collected": ("Misc", "Data Cells Collected"),
 "MS_Completed_Tutorial": ("Misc", "Tutorials Completed"),
}


def main():
    save = snapshot.find_save()
    if save is None:
        print("Save not found. Point DRG_SAVE at your .sav or pass it to snapshot.py.")
        return 1
    pak = find_pak()
    if pak is None:
        print("FSD-WindowsNoEditor.pak not found in any Steam library.")
        return 1

    # save: true stat guids present (16 bytes ending 4 before the "Value" FString)
    data = Path(save).read_bytes()
    save_guids = set()
    pos = 0
    while True:
        v = data.find(b"Value\x00", pos)
        if v < 0:
            break
        pos = v + 1
        if data.find(b"FloatProperty\x00", v, v + 40) >= 0 and v >= 20:
            save_guids.add(data[v - 20:v - 4].hex())

    f = open(pak, "rb")
    files, encoded = read_pak_files(f)
    assets = sorted({k[len(PREFIX):].rsplit(".", 1)[0] for k in files
                     if k.startswith(PREFIX) and k[len(PREFIX):].startswith("MS_")})

    out, unmapped = {}, []
    for a in assets:
        guid = None
        for ext in (".uexp", ".uasset"):
            path = PREFIX + a + ext
            if path not in files:
                continue
            blob = read_asset(f, files, encoded, path)
            for i in range(len(blob) - 16):
                g = blob[i:i + 16].hex()
                if g in save_guids:
                    guid = g
                    break
            if guid:
                break
        if guid is None:
            continue                                     # stat with 0 value / not in save
        cat, lab = CURATED.get(a, ("Misc", a[3:].replace("_", " ")))
        if a not in CURATED:
            unmapped.append(a)
        out[guid] = {"category": cat, "label": lab}
    f.close()

    dest = Path(__file__).resolve().parent.parent / "mission_stats.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {dest} with {len(out)} stats.")
    if unmapped:
        print(f"WARNING: {len(unmapped)} assets fell back to auto-labels: {unmapped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
