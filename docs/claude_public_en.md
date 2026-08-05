# DRG Stats Tracker — Project Technical Guide

> 🌐 **Language / Idioma:** English (this file) · **[Português](claude_public.md)**

> This file is the **project's technical map**: what exists, how it works, and why.
> Each section assumes only what came before it, so you can read it in order. Supporting
> documentation (with more detailed explanations) lives in `README.md` and `logica.md`.

---

## 1. What this project is (overview)

The game **Deep Rock Galactic** stores, in a save file, how many enemies of each
species you've killed over your account's lifetime (plus a whole pile of other stats).
The game only shows this inside the bestiary, one creature at a time, with no history and
no charts.

**What we're building:** a program that reads that save, extracts the numbers, stores them
in a local database every time it runs (building up a **history**), and finally shows
everything in a **dashboard with charts** (kills per species, evolution over time, etc.).

Why this is a good portfolio project: it brings together the three stages of real data
work — **extract** (from a raw binary format), **store** (database modeling), and
**visualize** (dashboard). It shows a recruiter that you're not afraid to dig into an
unknown format.

---

## 2. Minimal vocabulary (terms that show up in the project)

Before the files, the terms that come up constantly:

- **Script / `.py` file**: a text file with instructions Python executes top to bottom. It's the "recipe".
- **Variable**: a named box that holds a value. `x = 5` puts the number 5 in the box named `x`.
- **Function (`def`)**: a reusable mini-machine. You give it inputs, it returns an output. E.g.: `def double(n): return n*2`.
- **List `[ ]`**: an ordered queue of things. `[10, 20, 30]`.
- **Dictionary `{ }`**: **key → value** pairs, like a real dictionary (look up the word, find the definition). `{"grunt": 75466}`.
- **`import`**: bring code from another file to use here. Like borrowing a tool from another box.
- **Loop (`for` / `while`)**: repeat an action several times.
- **Byte**: the rawest form of data — a number from 0 to 255. **Every file on the computer is just a giant sequence of bytes.** Reading a "binary" format is interpreting that sequence.
- **Database / SQLite**: an organized way to store data in **tables** (like spreadsheets: rows and columns). SQLite keeps everything in a single local file, no server.
- **SQL**: the language to talk to the database. `SELECT` = get data, `INSERT` = store, `JOIN` = combine two tables by a shared column.

---

## 3. How the pieces connect (architecture)

The flow of data, left to right:

```
   game save              translate bytes         store with history         show it nicely
 (XXXXX_Player.sav)  ->  drg_save_parser.py  ->      snapshot.py        ->    dashboard.py
        │                       │                        │                        │
        │                       │                   drg_stats.db  <──────────────-┘
        │                       │                  (SQLite database)   (reads the database)
        │                       │
        └── all_drg_enemies.json ───┘  (translates the creature's internal ID -> readable name)
```

In words: the **parser** knows how to read the raw save. The **snapshot** uses the parser to
take a "photo" and write it to the **database**. The **dashboard** reads the database and
draws the charts. **all_drg_enemies.json** is the little lookup table that swaps internal
codes for creature names.

---

## 4. The save format (technical knowledge we've already discovered)

This part is gold — it was reverse-engineered by hand. Kept here so nobody has to
rediscover it.

- The file is a **GVAS** type (Unreal engine save format). The first 4 bytes are the letters `GVAS`.
- Numbers are stored in **little-endian** (from the least significant byte to the most significant — like writing "backwards"). E.g.: the number 75466 becomes the bytes `ca 26 01 00`.
- The save is a sequence of **properties**, each in the format: `[Name][Type][Size][Data]`.
- **Text** is stored as an **FString**: first a 4-byte number with the length, then the letters, ending in `\0`. (That's why, to find a property, we search for this exact encoding, not the bare word — otherwise "Level" would match inside "RetiredCharacterLevels".)
- The **`EnemiesKilled`** property is a **MapProperty** (a dictionary): the key is a 16-byte **GUID** (a unique enemy ID) and the value is the kill count (`IntProperty`, 4 bytes). There are **77 species**.
  - Map header layout: `Name` → `"MapProperty"` → `Size (int64)` → `"StructProperty"` (key type) → `"IntProperty"` (value type) → 1 flag byte → `int32 remove` → `int32 num_entries` → then the entries (each = 16 bytes of GUID + 4 bytes of count).
- **Loose scalars** (single number): `Credits`, `PerkPoints`, `NumberOfGamesPlayed`, `TotalPlayTimeSeconds`.
- **`OwnedResources`**: another map, GUID → `FloatProperty` value (resources you have). 22 entries. (Not used in the dashboard yet.)
- Confirmed reference: the GUID `e977bf0a42a9ed46a0d89c8d874adcff` = **Glyphid Grunt** (matched the in-game screenshot).

### 4.1 Account rank and promotions (⚠️ NOT scalars — they're DERIVED)

A big trap that already cost us a bug: **the account "Rank" (the big number in the
game, e.g. 115) and the total promotions are NOT stored as a ready-made number.**
There's even a property called `Level` in the save, but it's some loose "level" (it was
44 in testing) — it is **not** the rank. Reading `read_scalar("Level")` gives the wrong
number. Same for `read_scalar("TimesRetired")`: it only picks up the 1st class.

What the save actually stores is **one block per class** (Driller, Engineer, Gunner,
Scout). Each block is keyed by the **class GUID** (16 bytes, a fixed game constant) and
contains, in order: `XP (IntProperty)` → `TimesRetired (IntProperty)` →
`RetiredCharacterLevels (IntProperty)`. Details:

- **`TimesRetired` per class = the number of PROMOTIONS of that class.** The engine calls
  a promotion a "retire". Summing the 4 classes gives the total promotions (e.g. 1+3+3+3=10).
  (Careful: there's a 5th ghost block with GUID `6e68d5d6…`, XP 0 — ignore it.)
- **The class level (1–25) is DERIVED from XP**, it isn't stored. It uses DRG's cumulative
  XP table (`CLASS_XP_TABLE`), which caps at **315000 = level 25** (which unlocks the
  promotion). Confirmed: XP 282845→lvl 23, 300779→lvl 24, 315000→lvl 25.
- **Account rank** = `(sum of the total levels of the 4 classes) // 3`, where a class's
  "total level" = `RetiredCharacterLevels + current level`. E.g.:
  (25+24)+(75+25)+(75+23)+(75+25) = 49+100+98+100 = 347 → `347//3` = **115**. ✔
- **Class GUIDs** (confirmed by matching the bestiary/screenshot):
  Driller `9edd56f1…`, Engineer `85ef626c…`, Gunner `ae56e180…`, Scout `30d8ea17…`.

This lives in `parse_classes()` + `level_from_xp()` in the parser. `parse_save` returns
`player_rank`, `promotions`, and the `classes` list (per-class detail). The `level`/
`times_retired` keys were repurposed to rank/promotions (keeping the names for
compatibility with the database schema).

### 4.2 Missions completed vs. games played (⚠️ NOT `NumberOfGamesPlayed`)

Another trap, found on 2026-08-02: the game's stats screen shows **"Missions Completed"**
(445 in testing), but that number is **NOT** the scalar `NumberOfGamesPlayed`. That scalar
counts **every game started** — including abandoned/failed ones — and it was **504** in
the same save. Reading `NumberOfGamesPlayed` and labeling it "missions" gives 59 too many.

The "completed" one lives inside a **`MissionStatsSave`** block (right at the start of the
save), which is an array called `Counters`. **Each entry has 3 fields, in order:**
`PlayerClassID` (Guid, 16 bytes) → `MissionStatID` (Guid, 16 bytes) → `Value`
(`FloatProperty`, 4 bytes). So **each statistic is stored PER CLASS**; the total the game
displays is the **SUM of the 4 classes** for the same `MissionStatID`.

- Confirmed GUID for "missions completed": **`8ae243468b5da06e7bd0e4c806000000`**
  (sum = 445, matching the screenshot). Per class: Gunner 127 + Driller 70 +
  Engineer 114 + Scout 134 = 445. ✔ (The class GUIDs here match `CLASS_GUIDS`.)
- There are **95 distinct stats** in this block. **ALL are mapped now** (2026-08-04, via
  the `.pak` — see section 4.4). Missions per class: Gunner 127 + Driller 70 + Engineer 121
  + Scout 137 = **455** ✔ (the save grew from 445→455).

This lives in `parse_mission_stat(data, stat_guid)` + the `MISSIONS_COMPLETED_STAT`
constant in the parser. `parse_save` returns `missions_completed`. In the database it
became the `missions_completed` column (see section 6); in the dashboard it became the
"Missions completed" metric, next to "Games played" (the old 504).

### 4.3 Overclocks and cosmetics (what you HAVE vs the TOTAL)

The save stores **what you own**, not the game's catalog. Two lists matter:

- **`ForgedSchematics`** — an `ArrayProperty` of `StructProperty(Guid)`. These are the
  schematics you **forged**: weapon overclocks **+** cosmetics from matrix cores, all mixed
  together. In testing: **151 GUIDs**.
- **`UnLockedVanityItemIDs`** — same format. Unlocked cosmetics (**154**).

To turn this into "I have X of Y", you need the **catalog** (the Y), which is **not in the
save** — it comes from `guids.json` (the "reference table", just like `all_drg_enemies.json`
was for creatures). It has: `Weapons` (**160 overclocks**, with weapon/class/name/cost), and
cosmetics (`Headwear` 36, `Moustache` 44, `Beard` 144, `Sideburns` 28, `Victory Moves` 36,
`Weapon Skins` 60).

- **GUID encoding:** matches **directly on the UPPERCASE hex** (no byte-swap). Confirmed:
  100 of the 151 forged match the 160 overclocks → **overclocks: 100/160**. The other
  51 forged are matrix-core cosmetics.
- **⚠️ Cosmetics are uncertain:** the count comes out low (e.g. Headwear 1/36) because
  vanity unlocks have several sources (rank, pass, matrix core…) and `UnLockedVanityItemIDs`
  alone doesn't cover them all. In the dashboard the cosmetics section is marked as an
  **estimate**.
- Overclocks is solid. It lives in `parse_guid_array(data, name)` in the parser; `parse_save`
  returns `forged_schematics` and `vanity_items`. The **dashboard reads the CURRENT save**
  (not the database) and cross-references `guids.json` in the "⚙️ Overclocks" tab.

### 4.4 The 95 mission stats, mapped for good (via the `.pak`) ⭐

The "match by number" approach from 4.2 has a ceiling: **duplicate values = unresolvable
ambiguity** (e.g. 3 stats were worth 41). To settle it for good, we went to the **game
files**. The beginner-friendly explanation (from scratch) is in `logica.md` §11; here, the
technical summary (2026-08-04):

- **`Cargo Crates` and `Lost Equipment` do NOT exist as stats.** The game screen doesn't
  show them and there's no `MS_*` asset for them (the ASCII hits in the pak were **dwarf
  voice lines**). It **can't** be tracked — an honest, demonstrable answer.
- **Each stat is an asset** under `/Game/GameElements/KPI/MissionStats/MS_*` (e.g.
  `MS_Secondary_ApocaBloom`, `MS_Killed_TotalEnemies`), which contains the stat's GUID.
- **⚠️ GUID alignment in the save (subtle bug):** the true GUID is the **16 bytes that
  end 4 bytes BEFORE the FString `"Value"`** (`data[v-20:v-4]`). The final 4 bytes
  (`06000000`) are the **length prefix (int32=6)** of the word "Value", they're NOT part of
  the GUID. Anchoring on the wrong bytes made EVERY GUID "end in 06000000".
- **The pak** (`FSD-WindowsNoEditor.pak`, 2.4 GB) is a **UE4 pak v11, Zlib-compressed** (no
  Oodle) → readable in **pure Python** (`zlib`), no external tool. `tools/extract_mission_stats.py`
  parses the index, finds the `MS_*` assets, decompresses them, and **cross-references each
  asset's GUID with the save's GUIDs** (the save is the ground truth) → 95/95 with no
  guessing. Validations: `MS_TimePlayed` = 751632 s = 8d16h47m12s ✔; `MS_DistanceTravelled` =
  203212652 cm = 2032.1 km ✔; Scout+Gunner+Eng+Driller = 455 ✔.
- It becomes **`mission_stats.json`** (`guid → {category, label}`), the analog of
  `all_drg_enemies.json`. Categories: Overview, Mission Type, Biome, Class, Hazard, Secondary,
  Warning, Economy, Forging, Progression, Misc.
- **⚠️ Hazard: only TWO thresholds exist, and one is cumulative (2026-08-04).** The game
  only has the assets `MS_Completed_Hazard3` and `MS_Completed_Hazard5` — there is **no
  separate Hazard 1/2/4**. The asset's internal titles prove the semantics:
  `MS_Completed_Hazard3` = **"Missions Completed on Hazard 3 or Higher"** (CUMULATIVE —
  includes Haz 4 and 5!), and `MS_Completed_Hazard5` = "Missions Completed on Hazard 5".
  That's why "Hazard 3" read 371 on a save from someone who mostly plays Haz 4: the Haz 4
  games are counted in there. **Relabeled to `Hazard 3+`** in `CURATED` (extract) +
  `mission_stats.json`, with a `hazard_note` caption (EN/PT) in the tab explaining there is
  no Haz 4 stat.
- **⚠️ `MS_Killed_TotalEnemies` (KPI) ≠ the bestiary total (`EnemiesKilled`).** They are TWO
  distinct counters: the **bestiary** counts **lifetime** kills per species (sum = 191,445;
  Grunt alone = 81,049 → it's the "Total kills" of the species tabs). The **mission KPI** was
  only **65,642** — much lower (≈143 kills/mission, far too low for DRG). Likely reason: the
  MissionStats/KPI system was **added in a later game update**, so it only counts from then
  on; the bestiary counts since the account was born. **Not a bug** — different time windows.
  In the dashboard the Overview tile was renamed from "Total kills" to
  **"Enemies killed (mission stats)" / "Kills (stats de missão)"** (key `m_kills_ms`,
  separate from `m_kills` which stays the lifetime one), with the `overview_note` caption
  (EN/PT) explaining the difference and pointing to "Total kills" / the species tab.
- **In the dashboard:** the **"🎖️ Missions & Stats"** tab reads the CURRENT save (cached,
  like overclocks — NOT history) via `parse_mission_stats(data)` + cross-references the JSON.
  General metrics + bar charts per category + economy/forging/progression tables. Bilingual
  (stat labels stay in English, like creature/weapon names).

---

## 5. The files, one by one

### `drg_save_parser.py` — the save translator
**Purpose:** read the raw `.sav` file and return the data in organized form. Depends on
nothing external (only Python's standard library).

Main pieces (functions):
- `read_fstring(data, pos)` — reads text in FString format starting at a position.
- `find_property(data, name)` — finds where a property starts, matching the **exact**
  encoding of the name (avoids substring false positives).
- `read_scalar(data, name)` — reads a single number (Credits, PerkPoints, etc.).
- `parse_guid_map(data, name)` — reads a GUID→value map (works for `EnemiesKilled` **and** `OwnedResources`).
- `parse_classes(data)` — reads the 4 class blocks and returns level/promotions per class (see section 4.1).
- `level_from_xp(xp)` — converts a class's XP into the level 1–25 (`CLASS_XP_TABLE`).
- `parse_mission_stat(data, stat_guid)` — sums the `Value` of one `MissionStatID` across the classes (see section 4.2). Used for `missions_completed`.
- `parse_mission_stats(data)` — sums ALL 95 mission stats at once, returns `{guid: int}` (uses the correct GUID alignment, see section 4.4). Used by the "🎖️ Missions & Stats" tab.
- `parse_guid_array(data, name)` — reads an `ArrayProperty` of `StructProperty(Guid)` and returns the GUID list in UPPERCASE hex. Used for `ForgedSchematics` and `UnLockedVanityItemIDs` (see section 4.3).
- `parse_save(path, enemy_names=None)` — ties it all together and returns a **dictionary** with: `player_rank`, `promotions`, `classes`, `level` (=rank), `credits`, `perk_points`, `games_played` (=games played, 504), `missions_completed` (=missions completed, 445), `times_retired` (=promotions), `playtime_seconds`, `total_kills`, `species_count`, `kills_by_guid`, `kills_named`, `resources_by_guid`, `forged_schematics` (overclocks+forged cosmetics), `vanity_items` (cosmetics).
- `KNOWN_ENEMIES` — a minimal embedded GUID→name map (only the confirmed Grunt; the rest comes from `all_drg_enemies.json`).

How to run it standalone (prints a summary in the terminal):
```bash
python drg_save_parser.py "path/to/save.sav" all_drg_enemies.json
```

### `all_drg_enemies.json` — the creature translation table
A dictionary `{ "guid": "Creature name" }` with the 77 species. Built by cross-referencing
the kill **counts**: the bestiary screenshots gave (name → count), the save gave
(GUID → count), and the count served as the "glue" to link the two (a **JOIN** by count).

⚠️ **Known uncertainties** (see section 7):
- 3 names were deduced by elimination (OCR couldn't read the number): **Naedocyte Cave Cruiser (2487)**, **Maggot (331)**, **Silicate Harvester (39)**. Confirm by checking the in-game bestiary.
- 4 pairs have **identical** counts, so the GUID↔name pairing within the pair is a guess (cosmetic, since the number is the same): 247 (Ebonite Praetorian / Cave Leech), 38 (Hiveguard / Huuli Hoarder), 16 (Deeptora Honeycomb / Ossiran Bone Collector), 11 (Korlok Tyrant-Weed / Rival Tech Nemesis).

### `guids.json` — the overclock/cosmetic reference table
A big dictionary `{ category: { "GUID": {meta} } }` (see section 4.3). Categories:
`Weapons` (160 overclocks, with `dwarf`/`weapon`/`name`/`cost`), and cosmetics (`Cosmetic -
Headwear/Moustache/Beard/Sideburns`, `Victory Moves`, `Weapon Skins`). It's the "Y" of the
comparison — the save only says what you HAVE; this file says the TOTAL. GUID matches in
UPPERCASE hex against the save's `ForgedSchematics`.

### `mission_stats.json` — the reference table for the 95 mission stats **(NEW ✅)**
A dictionary `{ "guid": {"category": ..., "label": ...} }` with the **95 statistics** of the
`MissionStatsSave` block (see section 4.4). Built by reverse-engineering the `.pak`
(`tools/extract_mission_stats.py`), cross-referencing each `MS_*` asset's GUID with the
save's GUIDs. It's the "name" of the stats — the save only has the GUID and the value. Used
by the "🎖️ Missions & Stats" tab of the dashboard.

### `tools/extract_mission_stats.py` — the generator of `mission_stats.json` (reverse engineering) **(NEW ✅)**
Reads `FSD-WindowsNoEditor.pak` (UE4 pak v11, Zlib) in **pure Python** (only `zlib`, no
external tool): parses the pak index, finds the `MS_*` assets, decompresses them, and matches
each asset's GUID with the save's GUIDs (the save is the ground truth). Reuses
`snapshot._steam_libraries` to find the pak on any PC. Re-running regenerates
`mission_stats.json` from scratch. Pak format details in `tools/extract_mission_stats.md`.
See section 4.4 and `logica.md` §11.

### `snapshot.py` — takes the "photo" and stores it in the database
**Purpose:** run the parser, grab the numbers, and write ONE photo PER DAY into the SQLite
database (see section 6). Built to work on a fresh PC.

The smart things it does:
- **Finds the save on its own** (`find_save`) on ANY drive: besides the default paths, it reads the Steam registry + the `libraryfolders.vdf` (`_steam_libraries`) to find libraries on `D:`, `E:`, etc. It also accepts a path via argument / the `DRG_SAVE` variable. (It doesn't cover the Game Pass/Microsoft Store version — use `DRG_SAVE` there.)
- **Creates the database on the 1st run** (`conectar` runs the `SCHEMA_SQL` with `CREATE TABLE IF NOT EXISTS`).
- **Doesn't duplicate** (`tirar_snapshot`): if the last photo has the same kills and time, it doesn't write again (dedup).
- **ONE photo per DAY** (`tirar_snapshot` + `_data_local`): if the last photo is from TODAY (local date), it UPDATES it to the latest state instead of creating another. A lightweight database (1 row/day) and a clean day-to-day delta. See section 6.
- **Shows what grew** (`mostrar_deltas`) since the previous photo, comparing the last two.

How to run:
```bash
python snapshot.py                 # finds the save and takes a photo
python snapshot.py "path.sav"      # point at the save manually
python snapshot.py --loop 30       # takes a photo every 30 minutes
```
Needs `drg_save_parser.py` and (optionally) `all_drg_enemies.json` in the same folder.

### `watcher.py` — the save "watcher" (automatic capture) **(DONE ✅)**
**Purpose:** run in the background and take a photo ON ITS OWN — so nobody has to run
`snapshot.py` by hand. Reuses `snapshot.py`'s functions (`find_save`, `load_names`,
`conectar`, `tirar_snapshot`). Stdlib only.

It fires at the 3 key moments:
1. **game opens** → an opening photo (the session's baseline);
2. **save rewritten** → DRG rewrites the `.sav` at the end of a mission (back to the Space Rig);
   the watcher sees the modification date change and takes a photo (the **dedup** avoids
   writing duplicates, so the database doesn't bloat);
3. **game closes** → a final photo and the watcher exits on its own.

Game detection: it asks the OS whether the `FSD-Win64-Shipping.exe` process is alive
(`tasklist` on Windows, `pgrep` on Linux). If it can't detect it, it falls back to "file
mode" (runs until Ctrl+C or `--minutos`).

**How to make it 100% automatic (the practical trick):** via **Steam Launch Options**,
using the `drg_watcher_launch.bat` launcher. Easy way: run `configurar_steam.bat`
(double-click) — it builds the line with THIS PC's path and copies it to the clipboard;
then just paste it into Properties → General → Launch Options. The line looks like:
```
"C:\...\Papaio-Stats\drg_watcher_launch.bat" %command%
```
`%command%` is DRG itself (Steam swaps it in). The `.bat` starts the watcher hidden and
then hands over the game. So the watcher turns on together with DRG and the player just
clicks Play.

⚠️ **It did NOT work** to put the "clever" line `cmd /c start "" /min pythonw "...watcher.py" &
%command%` directly into Launch Options (Steam opened a cmd and ran nothing; `watcher.log`
wasn't even created). The `.bat` wrapper is the reliable way — tested.

Manual use / testing:
```bash
python watcher.py                 # finds the save, waits for the game, watches
python watcher.py --sem-processo --minutos 60   # file mode, stops after 60 min
python watcher.py --intervalo 5   # checks every 5s (default: 8)
```
Everything is logged to `watcher.log` (UTF-8). **Why it's NOT a mod.io mod:** DRG mods are
Blueprint in a closed sandbox — they can't read files, run Python, or open a browser. Only
NATIVE code (like the `mint` loader, in Rust, which injects a DLL) escapes this, and that's
too heavy/fragile for this project. That's why capture is external (this watcher), not a
mod. (See section 7.)

### `drg_watcher_launch.bat` — the Steam launcher **(DONE ✅)**
A 2-useful-line `.bat` that goes in the **Steam Launch Options** (see `watcher.py` above).
It does: `start "" /min pythonw "%~dp0watcher.py"` (starts the watcher hidden, next to the
`.bat` itself) and then `%*` (launches the game and holds while it runs, as Steam expects).
It's the **reliable** way to start the watcher along with the game — the loose `& %command%`
in Launch Options did not work. Tested.

### `configurar_steam.bat` — generates the Steam line and copies it to the clipboard **(DONE ✅)**
Solves the annoyance of typing the whole directory in Launch Options. It uses `%~dp0` to
figure out its own folder, builds `"<folder>\drg_watcher_launch.bat" %command%`, and dumps
it to the clipboard (via a temp file + `clip`, which avoids the space/line-break issues of
`echo | clip`). Double-click → paste into Steam with Ctrl+V. Works on any PC with no editing.
> Batch detail: to print a LITERAL `%command%` (without Steam expanding it), inside the
> `.bat` you write `%%command%%` — the `%%` becomes a single `%` in the output.

### `atualizar.py` + `atualizar.bat` — updating WITHOUT git **(DONE ✅ — 2026-08-04)**
`atualizar.py` (stdlib only: `urllib` + `zipfile`) downloads the repo's **ZIP from GitHub**,
extracts it, and **overlays** the code over the project. **No git, no pip** — Python is
already a prerequisite. Works the same whether the person cloned OR downloaded the ZIP.
- **Automatic data safety:** the GitHub ZIP contains only **tracked files**, so `drg_stats.db`,
  `*.sav` and `watcher.log` (gitignored) aren't even in the ZIP → the overlay can't touch them
  (it no longer depends on `.gitignore` at update time).
- **Marker `.update_check` (gitignored):** stores the synced commit SHA; the dashboard compares
  it with the remote SHA (GitHub API) to know whether an update exists.
- `atualizar.bat` is thin: it finds Python (`py`/`python`) and runs the `.py`. Its last line
  `%PY% atualizar.py & exit /b` — the `& exit /b` lets cmd quit **without re-reading** the `.bat`
  (which the update itself overwrites). The "press Enter" pause lives in the `.py`.

### `dashboard.py` — the dashboard with charts **(DONE ✅)**
Reads `drg_stats.db` and draws an interactive site: kill ranking per species, evolution of
metrics over time, credits, playtime, and "how much you killed since the last photo". Built
with **Streamlit** (a library that turns a Python script into a site) + **Altair** (charts) +
**pandas** (data tables). The latter two ship with Streamlit, so the only dependency to
install is Streamlit.

It has a **"📸 Update now"** button that reads the save and writes a new photo without a
terminal — reusing `snapshot.py`'s functions. It also has a **project update notice** in the
sidebar: the `checar_atualizacao()` function (now **git-free**) gets the branch's latest SHA
from the **GitHub API** (`atualizar.sha_remota()`) and compares it with the local marker
`.update_check`; if they differ, it shows **🔔 update available** telling you to run
`atualizar.bat`. On the first run it *baselines* (stores the SHA and shows "up to date") so it
doesn't nag right away. It's cached with `@st.cache_data(ttl=3600)` (checks at most once/hour)
and **fails silently** (`"indisponivel"`) with no internet. Works the same for clones and ZIP
downloads. Important study note: **the entire line-by-line explanation of this file
(functions, logic, Streamlit and Altair syntax, how to edit/reuse it) is in
[Section 11](#11-complete-guide-dashboardpy-and-streamlit).**

How to run (manual way):
```bash
pip install streamlit
streamlit run dashboard.py
```

### `abrir_dashboard.bat` — the double-click shortcut (Windows)
A `.bat` file (Windows command-prompt script). **Double-clicking it opens the dashboard**
with no terminal needed: it finds Python, installs Streamlit on the 1st run if it's missing,
and runs `streamlit run dashboard.py`. It's what makes the project usable by non-devs.
Explained line-by-line in Section 11.7.

### `.streamlit/config.toml` — the dashboard's fixed theme
A configuration file Streamlit **reads on its own** when it runs (the `.streamlit` folder at
the project root is a Streamlit convention). It holds the theme colors (black background, DRG
orange). Explained in Section 11.6.

### `renomeador.py` — a standalone utility (NOT part of the DRG pipeline)
Watches a folder and renames new images to 1, 2, 3... It's a separate tool, unrelated to the
DRG tracker pipeline. Ignore it when working on the tracker.

---

## 6. The database (schema explained)

There are **two tables** in a **one-to-many** relationship: one photo (`snapshots`) has
several count rows (`kills`).

```sql
snapshots ( id, taken_at, save_file, level, credits, perk_points,
            games_played, missions_completed, times_retired,
            playtime_seconds, total_kills )

kills ( snapshot_id, guid, name, count )      -- linked to snapshots by snapshot_id
```

> **Column migration:** `missions_completed` was added AFTER the database already existed.
> Since `CREATE TABLE IF NOT EXISTS` doesn't alter an existing table, `snapshot.py` has
> `_migrar()` (runs `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` for only what's missing —
> idempotent). Old photos get `missions_completed = NULL` (there's no way to know the
> historical value; **you don't fabricate history**). Only the photo matching the current
> save was backfilled with 445.

> **ONE photo per DAY (the write rule).** `tirar_snapshot` doesn't create a row per mission
> (that would fill up: 30 missions = 30 rows). If a photo from TODAY already exists (**local**
> date, via `_data_local`), it **updates** that row (UPDATE + swaps its kills) to the latest
> state; otherwise it creates a new one. Result: each day = the state at the **end** of the
> day, a lightweight database, and a day-to-day delta = "what I did that day". The dedup
> (don't write if nothing changed) still applies on top.

The ideas behind this (important):
- **We store facts, not derivatives.** The counts are saved; the "how much it grew" and the ranking are **computed on the fly** with SQL. Storing the delta would leave it stale. (Rule: *derived state is computed, not stored.*)
- **We always store the GUID + the name as optional (can be NULL).** The GUID is the stable key that always exists; the name is just enrichment and can be filled in later. That way even an unmapped creature is tracked.
- **Composite primary key** on `kills` = `(snapshot_id, guid)`: guarantees the same species can't appear twice in the same photo.

---

## 7. Traps and reminders (gotchas)

- **SQLite ignores FOREIGN KEY by default.** You have to run `PRAGMA foreign_keys = ON;` on **every** connection, otherwise the `ON DELETE CASCADE` doesn't happen and doesn't even error — it just silently doesn't work.
- **Never build SQL with an f-string.** Always use `?` (a parameterized query). It protects against SQL injection and handles quotes/commas/nulls correctly.
- **OCR is unreliable.** When reading a number off the screen, always **validate it against a set of values you know exist** (here: the save's own counts). A reading that doesn't match any valid value = discard it and try again.
- **Substring search in binary is dangerous.** Matching `"Level"` catches it inside `"RetiredCharacterLevels"`. Always match the exact encoding (length + text + `\0`).
- **A duplicate count = unresolvable ambiguity** from the data alone. That's why a unique key (PRIMARY KEY) matters. (The 4 pairs in section 5.)
- **`renomeador.py` is destructive** (renaming has no "undo"). Test on copies before pointing it at important photos.
- **`pythonw` has no console: `sys.stdout` can be `None`.** A `print()` in a process launched with `pythonw` (like the watcher via Steam) can blow up with `AttributeError`. That's why `watcher.py` logs to a FILE (UTF-8) and only tries the console guarded by `if sys.stdout is not None`.
- **The Windows console is cp1252: emoji break `print`.** Printing `📸`/`—` on the default console triggers `UnicodeEncodeError`. The log file is UTF-8 (handles everything); the console print goes inside a `try/except`.
- **The working directory isn't guaranteed.** When Steam launches the watcher, the CWD can be the GAME's folder. `watcher.py` does `os.chdir(script_folder)` at the start so `drg_stats.db`, `all_drg_enemies.json` and `watcher.log` land in the right place.
- **"Today" is the LOCAL date, not UTC.** The one-photo-per-day rule groups by the PC's timezone day (`_data_local` converts the UTC `taken_at` to local before taking `.date()`). If it grouped by UTC day, a 10pm session in Brazil (01:00 UTC the next day) would fall on the wrong day.
- **Overclocks come from the SAVE, not the database.** The comparison is CURRENT state, so the dashboard reads the save on the fly (cached with `@st.cache_data`) and cross-references `guids.json`. Consequence: on a PC WITHOUT the save (only the database), the overclock tab has nothing to show — that's why it has a "save not found" guard.
- **Store in UTC, DISPLAY in local.** `taken_at` is written in UTC (correct — it's timezone-neutral). But displaying requires converting to the PC's timezone, otherwise the dashboard shows London time (it showed 22:06 instead of 19:06 in Brazil). The classic mistake is `pd.to_datetime(x, utc=True).dt.tz_convert(None)` — that strips the timezone while KEEPING the UTC clock. Correct: `.dt.tz_convert(fuso_local).dt.tz_localize(None)`, with `fuso_local = datetime.now().astimezone().tzinfo` (grabs the PC's timezone on its own, no hardcoding).
- **`subprocess` under `pythonw` FLASHES a little window and steals focus.** Running via `pythonw` (no console), each `subprocess.run(["tasklist", ...])` opens a console window that appears for an instant and **steals focus** from the active window — unbearable if the watcher checks every few seconds. Fix: pass `creationflags=CREATE_NO_WINDOW` (0x08000000) to `subprocess` (Windows only). It's the `_SEM_JANELA` constant in `watcher.py`.
- **A DRG mod does NOT reach our pipeline.** mod.io mods are Blueprint in a closed sandbox (no file I/O, no process, no network). Only native code (e.g. the `mint` loader, in Rust, which injects a DLL and hooks the engine) breaks through — too heavy and fragile here. That's why automatic capture is `watcher.py` (external), not a mod.
- **Updating is git-free now (2026-08-04).** It used to depend on `git clone` + git being installed (a non-techie friend doesn't have it). Now `atualizar.py` (pure Python) downloads the GitHub ZIP and overlays it. What saves the data is no longer `.gitignore` but the fact that **the GitHub ZIP only contains tracked files** — database/log/`.sav` aren't in it. Works for clones AND ZIP downloads.
- **⚠️ `atualizar.bat` overwrites itself.** `atualizar.py` rewrites the `.bat` during the update; its last line `%PY% atualizar.py & exit /b` makes cmd quit without re-reading the file (the `& exit /b` is parsed together, before Python runs). Nothing may go after that line; the pause lives in the `.py`.
- **A networked update check on every re-run would kill performance.** Streamlit re-runs the whole script on every interaction (section 11.0). Fix: `@st.cache_data(ttl=3600)` (at most once/hour) + a `timeout` on the **GitHub API** call (`urllib`, no longer `git`/`subprocess`) + fails silently (`"indisponivel"`) with no internet. On the first run `checar_atualizacao()` baselines the SHA into `.update_check` so it doesn't show 🔔 for no reason.

---

## 8. Project status

**Done:**
- [x] Confirmed the save contains kills per species (reverse-engineering the GVAS format).
- [x] `drg_save_parser.py` — extracts kills, resources and scalars. Tested.
- [x] `all_drg_enemies.json` — 77 GUIDs translated (with the caveats in section 5/7).
- [x] `snapshot.py` — writes photos to SQLite, finds the save on its own, doesn't duplicate, shows deltas. Tested.
- [x] **`dashboard.py`** (Streamlit) — metrics with variation, ranking per species, time evolution, deltas, table with search and CSV export. "Update now" button. DRG theme. Tested (starts with no error, reads the real data).
- [x] `abrir_dashboard.bat` + `.streamlit/config.toml` — double-click opens the dashboard; fixed theme.
- [x] **`missions_completed`** (missions completed, 445) — discovered in the `MissionStatsSave` block (section 4.2). Separated from `games_played` (games played, 504). Parser + database column (with migration) + dashboard metric. Tested.
- [x] **`watcher.py`** — watches the save and takes a photo on its own (opening / end of mission / closing). Logs to a UTF-8 file, anchors the CWD, detects the game process without flashing a window (`CREATE_NO_WINDOW`). Tested (the 3 triggers + dedup). See section 5/7.
- [x] **`drg_watcher_launch.bat` + `configurar_steam.bat`** — Steam launcher (starts watcher + game) and Launch-Options line generator (copies to clipboard). Tested.
- [x] **Timezone in the dashboard** — now displays in the PC's LOCAL timezone (was UTC). See the gotcha in section 7.
- [x] **Overclock comparison** ("⚙️ Overclocks" tab): 100/160 per weapon, progress bar, list of what's left to forge. Reads the current save + cross-references `guids.json`. Cosmetics as an estimate. See section 4.3. Tested.
- [x] **One photo per day** (`tirar_snapshot` updates today's photo instead of adding up). Lightweight database, clean day-to-day delta. See section 6. Tested.
- [x] **Plug-and-play on any PC** — `find_save` finds DRG on any drive (Steam registry + `libraryfolders.vdf`, via `_steam_libraries`). All paths auto-located (`%~dp0`, `os.chdir`, automatic timezone). The only prerequisite: Python installed. Tested (finds libraries on other drives).
- [x] **GitHub-ready** — `README.md` (overview + install + credits), `logica.md` (the reverse engineering explained from scratch, byte by byte) and `.gitignore` (ignores `drg_stats.db`, `watcher.log`, `*.sav`, `__pycache__`, `mint-master/`, personal screenshots).
- [x] **Git-free auto-update (2026-08-04)** — `atualizar.py` (pure Python: downloads the GitHub ZIP and overlays it) + a thin `atualizar.bat` (finds Python and runs the `.py`; self-modify-safe via `& exit /b`). The **🔔 update available** notice compares the remote SHA (GitHub API) with the local marker `.update_check` (baselined on first run). **Works for clones AND ZIP downloads, no git or pip.** Data is preserved because it isn't in the ZIP. Documented in `README.md` (EN/PT). See section 5/7. Tested (real sha_remota + download + ZIP parse; AppTest EN/PT).
- [x] **Bilingual (EN/PT)** — `README.md` and `logica.md` have English first, Portuguese after. **Code comments and docstrings translated to English** (parser, snapshot, watcher, dashboard, `.bat`s). The internal technical documentation stays in PT. The dashboard `.bat` is named `abrir_dashboard.bat` (lowercase).
- [x] **Bilingual dashboard with a language selector (2026-08-03)** — the UI opens in **English** (default) and has the **🌐 Language / Idioma** selector in the sidebar (EN/PT live). Reason: Reddit users complained about the PT-only UI. Texts in the `TEXTS` dict (EN/PT); number/date formatters switch per language. Tested (AppTest EN/PT).
- [x] **Naedocyte Hatchling fix (2026-08-03)** — the GUID `d805ddff…` was labeled "Cave Cruiser" (deduced) but it's the **Naedocyte Hatchling** (Cave Cruiser is docile, no kills). Fixed in `all_drg_enemies.json` + backfill in the database. See section 5.
- [x] **The 95 mission stats mapped via the `.pak`** (2026-08-04) — `mission_stats.json` + `tools/extract_mission_stats.py` (a pure-Python UE4 pak v11/Zlib reader) + `parse_mission_stats()` in the parser + the bilingual **"🎖️ Missions & Stats"** tab. Correct GUID alignment (`data[v-20:v-4]`). Confirmed that Cargo Crates/Lost Equipment don't exist as stats. See section 4.4. Tested (AppTest EN/PT).
- [x] **Hazard relabel + kills-axis fix + KPI vs bestiary tile (2026-08-04)** — the mission bar charts said "Kills" on the x-axis (they reuse the species-kill chart); added an `x_label` param → "Missions"/"Missões". Relabeled "Hazard 3" → "Hazard 3+" (it's cumulative, includes Haz 4) with a `hazard_note` caption. Renamed the Overview "Enemies killed" tile to make clear it's the mission-stats KPI counter (much lower than the lifetime bestiary total), with an `overview_note` caption. See section 4.4. Tested (AppTest EN/PT).

**To do:**
- [ ] Cosmetics: a reliable count (map the other vanity sources beyond `UnLockedVanityItemIDs`).
- [ ] Nail down the exact Steam Launch Options line (test the quotes/`%command%`) and a step-by-step in the README.
- [ ] Confirm the 2 remaining deduced names in the bestiary (Maggot / Silicate Harvester). (Naedocyte "Cave Cruiser" already resolved: it was the Hatchling.)
- [x] ~~Map the other `MissionStatsSave` stats~~ — DONE, all 95 (section 4.4).
- [ ] (Optional) A `resources` table in the database, same pattern as `kills`.
- [ ] (Optional) Schedule `snapshot.py` (Task Scheduler on Windows / cron or systemd on Arch).
- [x] ~~Map GUID→name from the `.pak` files~~ — DONE for the mission stats (section 4.4); the same technique can still be used on the ambiguous creature pairs.
- [ ] A polished README telling the story (reverse engineering → ETL → dashboard).

---

## 9. How to run the project from scratch

```bash
# 1. Have Python 3.10+ installed.
# 2. Put drg_save_parser.py, all_drg_enemies.json and snapshot.py in the same folder.

# 3. Take the first photo (creates the database drg_stats.db):
python snapshot.py

# 4. (Optional) Automatic capture while you play:
#    - run configurar_steam.bat (double-click) -> copies the line to the clipboard
#    - paste it into Steam -> DRG -> Properties -> Launch Options
#    (or, by hand: python watcher.py)

# 5. Open the dashboard — the EASY way (Windows): double-click "abrir_dashboard.bat".
#    The manual way (any OS):
pip install streamlit
streamlit run dashboard.py
```
Only `dashboard.py` needs an external library (Streamlit; pandas and altair ship with it).
Parser, snapshot and watcher run on pure Python.

---

## 10. Quick glossary

- **GVAS**: the Unreal engine save file format.
- **GUID**: a 16-byte unique identifier (here, each enemy's "code").
- **little-endian**: byte order with the least significant byte first.
- **parser**: a program that reads and interprets a data format.
- **ETL**: Extract-Transform-Load — the arc of a data pipeline.
- **snapshot**: a "photo" of the data at an instant; put several together and you get history.
- **schema**: the design of the database tables (names, columns, types, keys).
- **JOIN**: combine two tables by a shared column.
- **PK / FK**: Primary Key (the unique key that identifies the row) / Foreign Key (a column that points to another table).
- **idempotent**: running it once or 100 times gives the same result (e.g. `CREATE TABLE IF NOT EXISTS`).
- **parameterized query**: SQL with `?` in place of the values, filled in safely by the driver.
- **Streamlit**: a library that turns a Python script into an interactive site, no HTML/JS.
- **Altair**: a charting library based on the "grammar of graphics" (you describe the data, it draws it).
- **DataFrame**: pandas's "spreadsheet in memory" — rows and columns, with a name on each column.
- **widget**: an interactive control on screen (button, slider, selectbox…).

---

## 11. Complete guide: `dashboard.py` and Streamlit

This section is the detailed guide to the dashboard. Read it in order; each part assumes the
previous one. By the end you'll be able to **read, edit and reuse** any piece of
`dashboard.py`.

### 11.0 The most important Streamlit idea (read this BEFORE anything else)

Streamlit has **one** central concept, and if you get it, the rest is easy:

> **Every time you touch anything on the screen, Streamlit RE-RUNS your entire script,
> top to bottom, from scratch.**

There's no "where's the code that responds to the button click?" like in other languages.
That doesn't exist. The Streamlit way is: the whole script runs, drawing the screen in the
order the `st.*` functions appear. You click a slider → Streamlit runs the WHOLE script
again, and now the slider's variable has the new value → the screen comes out different.

Practical consequences (memorize these three):
1. **The order of the lines = the order of things on the screen.** `st.title(...)` before
   `st.dataframe(...)` means the title on top, the table below. Want to change the layout?
   Change the order of the lines.
2. **Normal variables don't "remember" between re-runs.** Each re-run starts from scratch.
   To remember something between one click and the next, there's `st.session_state` (a
   dictionary that survives) — we use it to pass the "Update now" button's message (§11.4).
3. **An `st.button(...)` returns `True` only on the exact re-run caused by the click** — on
   the next re-run it's already back to `False`. That's why the pattern is always
   `if st.button(...):` with the action right inside the `if`.

This explains why `dashboard.py` is written "top to bottom, no main function": the file
itself, read in order, **is** the page.

### 11.1 The file map (what comes in what order)

```
1. imports                     -> brings in streamlit, altair, pandas and our snapshot.py
2. COLOR constants             -> the theme's palette (§11.5)
3. DATABASE ACCESS functions   -> conectar / carregar_snapshots / carregar_kills / carregar_deltas
4. FORMATTER functions         -> fmt_num / fmt_horas / fmt_quando (nice numbers)
5. atualizar_agora() function  -> what the 📸 button calls (uses snapshot.py)
6. CHART functions (Altair)    -> grafico_barras_especies / grafico_evolucao
7. "APPLICATION" (the body)    -> from here down is the page itself, in screen order:
     set_page_config -> CSS -> title -> empty-database guard ->
     sidebar -> metrics -> tabs (species / evolution / since / table)
```

Notice the pattern: **first we define tools (functions), then we use them** in the body.
That keeps the body short and readable — you can read the body like a script.

### 11.2 The database access functions (pandas + SQLite)

```python
def conectar() -> sqlite3.Connection | None:
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```
- **`Path(DB_PATH).exists()`**: checks whether the database file exists. If not, we return
  `None` — the body handles that by showing the "take the first photo" screen.
- **`sqlite3.connect(...)`**: opens the database. The dashboard only READS (the writer is `snapshot.py`).
- **`row_factory = sqlite3.Row`**: makes each row accessible by column name. Not strictly
  necessary here (pandas handles it), but good practice.

```python
def carregar_snapshots(conn) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM snapshots ORDER BY id ASC", conn)
    if not df.empty:
        fuso_local = datetime.now().astimezone().tzinfo
        df["quando"] = (pd.to_datetime(df["taken_at"], utc=True)
                        .dt.tz_convert(fuso_local).dt.tz_localize(None))
    return df
```
- **`pd.read_sql_query(sql, conn)`**: runs the SQL and returns the result already as a
  **DataFrame** (the "spreadsheet in memory"). It's the SQLite → pandas bridge.
- **`df["quando"] = ...`**: creates a NEW column in the DataFrame. `taken_at` is stored as
  ISO text **in UTC** (e.g. `"2026-08-01T01:31:23+00:00"`). `pd.to_datetime(..., utc=True)`
  turns it into a real date/time; `.dt.tz_convert(fuso_local)` brings it to the PC's timezone
  (otherwise the dashboard would show London time); `.dt.tz_localize(None)` strips the
  timezone (makes it "naive") for Altair/strftime. `fuso_local` comes from
  `datetime.now().astimezone().tzinfo`. (See the "Store in UTC, DISPLAY in local" gotcha in
  section 7.)

```python
def carregar_kills(conn, snapshot_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT guid, name, count FROM kills WHERE snapshot_id = ? ORDER BY count DESC",
        conn, params=(snapshot_id,))
    df["especie"] = df["name"].fillna("GUID:" + df["guid"].str.slice(0, 8))
    return df
```
- **`params=(snapshot_id,)`** with the `?` in the SQL = a **parameterized query** (the golden
  rule of section 7: never build SQL with an f-string). The comma in `(snapshot_id,)` is
  mandatory — it's what makes Python understand it's a 1-element tuple.
- **`df["name"].fillna(...)`**: `name` can be NULL (a creature without a translation). `fillna`
  fills those blanks. `df["guid"].str.slice(0, 8)` takes the first 8 characters of the GUID.
  Result: if there's a name, show the name; if not, show `GUID:e977bf0a`. That way the screen
  is never left with an empty cell.

```python
def carregar_deltas(conn, id_atual, id_anterior) -> pd.DataFrame:
    # ...SELECT with a LEFT JOIN between the current photo (k2) and the previous one (k1)...
    # delta = k2.count - COALESCE(k1.count, 0)
```
- This is the **same JOIN** `snapshot.py` uses in `mostrar_deltas`, just returning a DataFrame
  for the dashboard. `COALESCE(k1.count, 0)` = "if this creature didn't exist in the old
  photo, count it as 0" (e.g. a brand-new species). Note that I used
  `params={"ant":..., "atu":...}` — you can parameterize by **name** (`:ant`) instead of by
  position (`?`); both ways are valid.

### 11.3 The formatters (giant number → readable in the BR format)

```python
def fmt_num(n) -> str:
    if n is None: return "—"
    return f"{int(n):,}".replace(",", ".")
```
- **`f"{int(n):,}"`**: the `:,` inside an f-string is a Python "mini-format" that adds the
  thousands separator. `75466` becomes `"75,466"`. Since Python's default is a comma (US) and
  we want a dot (BR), I swap it with `.replace(",", ".")` → `"75.466"`.
- `fmt_horas` does the same with a `replace` dance to become `"34,3 h"` (a decimal comma).
  The `"X"` trick in the middle is just so it doesn't swap dot and comma on top of each other.
- **How to reuse:** any number you put on screen, pass it through `fmt_num(...)` to get the
  Brazilian format. (Note: the dashboard is bilingual now — the formatters switch the
  thousands/decimal separators per language; see the `TEXTS` dict and the language gotcha in
  the internal CLAUDE.md.)

### 11.4 `atualizar_agora()` — the button that writes a photo without a terminal

```python
def atualizar_agora() -> str:
    save_path = snapshot.find_save()
    if save_path is None or not save_path.exists():
        return "❌ Save not found..."
    names = snapshot.load_names()
    conn = snapshot.conectar(DB_PATH)
    try:
        snap_id = snapshot.tirar_snapshot(conn, save_path, names)
    finally:
        conn.close()
    if snap_id is None:
        return "ℹ️ Nothing changed..."
    return f"✅ New photo saved (snapshot #{snap_id})! ..."
```
- **The big trick:** instead of rewriting the save-writing logic, we **imported `snapshot.py`**
  (`import snapshot` at the top) and called its functions: `find_save`, `load_names`,
  `conectar`, `tirar_snapshot`. Pure reuse — the dashboard just "presses the buttons" of the
  module that already exists and was tested.
- **`try/finally`** guarantees the database is closed (`conn.close()`) even if something errors
  in the middle. It's the safe way to work with a file/connection.
- The function returns a **message string** (it doesn't draw anything). The body does the
  drawing, with `st.info(msg)`. Separating "doing" from "showing" makes the function testable.

How this becomes interaction (in the body, inside the sidebar):
```python
if st.button("📸 Update now", type="primary", width='stretch', help="..."):
    with st.spinner("Reading the save..."):
        msg = atualizar_agora()
    st.session_state["_msg_atualizar"] = msg
    st.rerun()
if "_msg_atualizar" in st.session_state:
    st.info(st.session_state.pop("_msg_atualizar"))
```
- **`st.button(...)`** returns `True` on the click's re-run → enters the `if`.
- **`with st.spinner("..."):`** shows a "loading" spinner while the block runs.
- Here `st.session_state` shows up (§11.0, point 2): I store the message in it and call
  **`st.rerun()`** (re-runs the script right away so the screen reflects the new photo). Since
  `st.rerun()` starts everything over, if I showed the message before it, it would vanish; so
  I store it in `session_state`, and on the next re-run I read it and remove it with `.pop(...)`
  (shows it once and clears it). It's the "message that survives a rerun" pattern.

### 11.5 The charts with Altair (the "grammar of graphics")

Altair works differently from how we usually imagine "making a chart". You **don't** say
"draw a bar at pixel X". You **describe the data**: "the Y axis is the species, the X axis is
the count, the color represents the magnitude" — and Altair draws it. This is called the
*grammar of graphics*. The three pieces are always:

1. **`alt.Chart(data)`** — which DataFrame the data comes from.
2. **`.mark_*()`** — the shape of the drawing: `mark_bar` (bar), `mark_line` (line),
   `mark_text` (text), `mark_point`…
3. **`.encode(...)`** — the **mapping**: which column goes to which "channel" (x, y, color,
   tooltip…).

The bar chart:
```python
def grafico_barras_especies(df, top_n):
    d = df.head(top_n).copy()
    base = alt.Chart(d).encode(
        y=alt.Y("especie:N", sort="-x", title=None, axis=alt.Axis(...)),
        x=alt.X("count:Q", title="Kills", axis=alt.Axis(..., format="~s")),
    )
    barras = base.mark_bar(cornerRadiusEnd=4, height=alt.RelativeBandSize(0.72)).encode(
        color=alt.Color("count:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None),
        tooltip=[alt.Tooltip("especie:N", title="Species"),
                 alt.Tooltip("count:Q", title="Kills", format=",")],
    )
    rotulos = base.mark_text(align="left", dx=4, ...).encode(text=alt.Text("count:Q", format=","))
    altura = max(120, len(d) * 26)
    return (barras + rotulos).properties(height=altura).configure_view(strokeWidth=0)...
```
Decoding each piece:
- **`df.head(top_n)`**: takes only the first `top_n` rows (the DataFrame already came ordered
  by count). It's the sidebar slider controlling how many bars appear.
- **`"especie:N"`** and **`"count:Q"`**: the suffix tells Altair the data's TYPE. `:N` =
  *Nominal* (a category, text: creature names). `:Q` = *Quantitative* (a number). `:T` =
  *Temporal* (date/time, used in the line chart). Getting the type right is what makes the
  axis come out correct.
- **`sort="-x"`** on the Y axis: orders the species by the X value, descending. That's what
  puts the biggest bar on top.
- **`format="~s"`** on the X axis: "short" notation (10000 → `10k`). **`format=","`** on the
  tooltip: thousands separator (here I left it in US style for tooltip simplicity).
- **`color=alt.Color("count:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None)`**: color
  represents MAGNITUDE. `RAMP_LARANJA` is a list of oranges from light to dark — bigger bar,
  stronger orange. **`legend=None`** removes the color legend (the bar explains itself).
  *Here's the dataviz rule I followed:* magnitude = **a single hue**, varying from light to
  dark (a sequential ramp), never a different color per bar (that would be "rainbow" and give
  the false impression that color is a category).
- **Layering:** `base.mark_bar(...)` draws the bars and `base.mark_text(...)` draws the number
  at the tip. The **`(barras + rotulos)`** with the `+` operator **stacks the two layers in
  the same chart**. That `+` is an Altair feature (overlaying layers).
- **`altura = max(120, len(d) * 26)`**: dynamic height — ~26px per bar, minimum 120. Without
  it, with 77 species the bars would be squashed flat.

The line chart (`grafico_evolucao`) follows the same recipe, with `mark_line` and the temporal
X axis (`"quando:T"`). I used one color per metric (orange for kills, yellow for credits, etc.)
because here each chart is a SINGLE line — color is just visual identity, not a category.

**How to edit/reuse the charts:**
- Change the bar color: touch the `RAMP_LARANJA` list (§11.6).
- Vertical bars instead of horizontal: swap the roles of X and Y (`x="especie:N"`,
  `y="count:Q"`).
- A new line chart of another metric: call `grafico_evolucao(snaps, "database_column",
  "Title", "#color")`. It works for any numeric column of `snapshots`.

> Note: the mission-stat bar charts reuse `grafico_barras_especies` via `grafico_categoria`,
> passing an `x_label` argument ("Missions"/"Missões") so the axis doesn't wrongly say "Kills".

### 11.6 The theme (colors) — in TWO places

The dark "cave" look comes from two files, and it's good to know why:

1. **`.streamlit/config.toml`** — Streamlit reads this file **on its own** at startup (the
   `.streamlit` folder at the project root is its convention). It defines the base theme of
   the default components (background, primary color of buttons/sliders, text color):
   ```toml
   [theme]
   base = "dark"
   primaryColor = "#eb6834"
   backgroundColor = "#12100e"
   secondaryBackgroundColor = "#1c1917"
   textColor = "#f5efe6"
   ```
   Touch this, and the overall look changes. **You need to restart** `streamlit run` for it
   to take effect.

2. **CSS injected in `dashboard.py`** — for things `config.toml` can't reach (making the
   metric cards have rounded borders, painting the metric number orange). This is done with:
   ```python
   st.markdown("<style> ... </style>", unsafe_allow_html=True)
   ```
   **`st.markdown`** normally writes text; with **`unsafe_allow_html=True`** it accepts raw
   HTML/CSS. Selectors like `[data-testid="stMetricValue"]` target Streamlit's internal
   pieces. It's called "unsafe" because raw HTML can be dangerous if it came from a user; here
   the text is ours, so it's safe.

The `COR_*` constants and `RAMP_LARANJA` at the top of `dashboard.py` are the single source
of the CHART colors (Altair doesn't read `config.toml`). Want to repaint everything? Touch
those constants + `config.toml`.

### 11.7 The page body, top to bottom (the script)

- **`st.set_page_config(page_title=..., page_icon="🪨", layout="wide")`** — must be the FIRST
  `st.*` call in the script. `layout="wide"` uses the full screen width.
- **Empty-database guard:**
  ```python
  if conn is None or carregar_snapshots(conn).empty:
      st.warning(...); ...; st.stop()
  ```
  If there's no database/photos, it shows the "take the first photo" screen and **`st.stop()`**
  ends the script right there (it doesn't try to draw charts without data). It's the Streamlit
  way of doing "early return".
- **The sidebar:** everything inside `with st.sidebar:` appears in the left sidebar.
  - **`st.selectbox("Photo (snapshot)", list)`** — a selectbox to choose which photo to look
    at. I built the options with a *dict comprehension* (`{text: id ...}`) and use the chosen
    text to find the `id`. `snaps.iloc[::-1]` reverses the order (newest on top);
    `.itertuples()` walks the DataFrame rows one by one.
  - **`st.slider("How many species to show", 5, 77, 20)`** — a slider: minimum 5, maximum 77,
    initial value 20. The return becomes the `top_n` variable used in the charts.
- **The metrics (the number header):**
  ```python
  c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
  c1.metric("Account rank", fmt_num(linha["level"]), delta_de("level"))
  ```
  - **`st.columns(7)`** creates 7 side-by-side columns; each `c1..c7` is a column where we put
    things. That's how you do horizontal layout in Streamlit. (It was 6; it became 7 when we
    split "Missions completed" from "Games played" — see section 4.2.)
  - **`.metric(label, value, delta)`** draws that card with a big number and a **little arrow**
    of variation (the 3rd argument). If the delta is positive it shows a green ↑, negative a
    red ↓, and if it's `None` no arrow appears.
  - **`delta_de(column)`** (a function defined in the body) computes the variation vs. the
    previous photo. The "find the previous photo" logic uses a DataFrame filter:
    `snaps[snaps["id"] < snap_id]` takes all photos with a smaller id, and `.iloc[-1]` takes
    the last of them (the immediately previous one). If there's no previous one, the delta is
    `None` (no arrow).
- **The tabs:**
  ```python
  aba_especies, aba_tempo, aba_desde, aba_tabela = st.tabs(["🐛 By species", ...])
  with aba_especies:
      st.altair_chart(grafico_barras_especies(kills, top_n), width='stretch')
  ```
  - **`st.tabs([...])`** creates clickable tabs and returns one object per tab; each tab's
    content goes inside `with aba_x:`.
  - **`st.altair_chart(chart, width='stretch')`** drops an Altair chart on screen.
    `width='stretch'` = "take the container's full width". (This used to be
    `use_container_width=True`; Streamlit renamed it. If a deprecation warning ever shows up,
    this is where you adjust it.)
  - **The Evolution tab** only makes sense with 2+ photos, so it has `if len(snaps) < 2:`
    showing a friendly notice. With history, it draws 4 lines (kills, credits, rank, time) in
    two rows of `st.columns(2)`.
  - **The Table tab:** **`st.text_input("🔎 Search species")`** is the search box; I filter the
    DataFrame with `tabela[tabela["Species"].str.contains(busca, case=False)]`.
    **`st.dataframe(...)`** shows the interactive spreadsheet (you can sort by clicking a
    column). **`st.download_button(...)`** generates the CSV on the fly with
    `tabela.to_csv(...).encode("utf-8")` and offers it for download — good for the portfolio
    (shows you thought about exporting data).

### 11.8 The Streamlit syntax I used — quick reference table

| Function | What it does | How to reuse |
|---|---|---|
| `st.set_page_config(...)` | tab title/icon/layout | 1st `st.*` call; `layout="wide"` for full screen |
| `st.title` / `st.subheader` / `st.header` / `st.caption` | texts of different sizes | pass a string; accepts markdown |
| `st.markdown(txt, unsafe_allow_html=True)` | rich text / inject CSS | with `unsafe_allow_html` it accepts raw HTML |
| `st.write` | the "swiss army knife" that shows almost anything | `st.write(anything)` |
| `st.metric(label, value, delta)` | a number card with an arrow | 3rd arg is the variation (optional) |
| `st.columns(n)` | n side-by-side columns | `c1,c2 = st.columns(2)`; use `c1.something(...)` |
| `st.tabs([...])` | tabs | content inside `with aba:` |
| `st.sidebar` | the sidebar | `with st.sidebar:` |
| `st.button(txt)` | a button; `True` on the click | always inside `if st.button(...):` |
| `st.selectbox` / `st.slider` / `st.text_input` | input widgets | the return is the chosen value |
| `st.altair_chart(g, width='stretch')` | draws an Altair chart | `width='stretch'` = full width |
| `st.dataframe(df)` | an interactive table | `column_config=` to format columns |
| `st.download_button` | download a file | pass bytes + `file_name` + `mime` |
| `st.spinner("...")` | "loading" | `with st.spinner("..."):` around the work |
| `st.info` / `st.warning` / `st.success` | colored notice boxes | pass the message |
| `st.session_state` | memory between re-runs | it's a dict: `st.session_state["key"]` |
| `st.rerun()` | re-runs the script now | use after changing state the screen should reflect |
| `st.stop()` | ends the script here | "early return" when there's nothing to show |

### 11.9 How to make the most common edits (recipes)

- **Add a new metric to the header:** increase the number in `st.columns(N)` and add a line
  `cX.metric("Label", fmt_num(linha["database_column"]), delta_de("database_column"))`. It only
  works if the column exists in the `snapshots` table.
- **Change the whole dashboard's accent color (orange):** change `primaryColor` in
  `config.toml` **and** the `COR_LARANJA` constant / the `RAMP_LARANJA` list in `dashboard.py`
  (config = components; constants = charts).
- **Show more/fewer species by default:** the `20` in `st.slider("...", 5, 77, 20)` is the
  initial value; the `5` and the `77` are the limits.
- **Add an evolution chart for another metric:** inside the Evolution tab, call
  `st.altair_chart(grafico_evolucao(snaps, "column", "Title", "#color"), width='stretch')`.
- **Change the tabs' order/names:** touch the list passed to `st.tabs([...])` (remember to
  rename the variables that receive the return, too).

### 11.10 Dashboard-specific gotchas (so you don't trip)

- **`streamlit run dashboard.py`, never `python dashboard.py`.** Running with `python`
  directly triggers "missing ScriptRunContext" warnings and doesn't open the site — Streamlit
  needs its own launcher. (The `.bat` already does it right.)
- **Changed `config.toml`? Restart** `streamlit run` (Ctrl+C and run it again). The theme is
  only read at startup. Changes to the `.py`, on the other hand, reload on their own (there's
  a "Rerun" button).
- **`st.button` doesn't "stay pressed".** It's `True` only on the click's re-run. You can't do
  `x = st.button(...)` and check `x` several screens later — to remember something, use
  `st.session_state`.
- **Altair types (`:N`, `:Q`, `:T`) matter.** Marking a number as `:N` makes Altair treat each
  value as a category and the axis comes out wrong. A date has to be `:T`.
- **The dashboard only READS the database; the writer is `snapshot.py`** (or the button that
  calls it). If the data looks old, it's because a new photo hasn't been taken — click 📸
  Update now.
- **The folder needs everything together:** `dashboard.py`, `snapshot.py`, `drg_save_parser.py`,
  `all_drg_enemies.json`, `drg_stats.db` and the `.streamlit/` folder. The dashboard's
  `import snapshot` depends on the other `.py` files being right there next to it.
