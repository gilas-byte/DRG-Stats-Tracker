# `extract_mission_stats.py` — reading the DRG `.pak` in pure Python

> 🇬🇧 **English** first · 🇧🇷 **Português** [further down](#-lendo-o-pak-do-drg-em-python-puro)

This tool recovers the **name of every mission statistic** by reading Deep Rock Galactic's
own game archive (`FSD-WindowsNoEditor.pak`) and writing `mission_stats.json`. It needs
**only the Python standard library** (`zlib`, `struct`) — no external unpacker.

For the *why* and the beginner-friendly story, read [`docs/logica.md` §11](../docs/logica.md).
This file is the *how* — the byte-level walkthrough of the pak format, for when you want to
understand or modify the code.

---

## The problem in one line

The save stores each stat as `GUID → number`, never the name. Matching names by number
fails when stats share a number (three stats = 41). So we read the names from the game files,
where each stat is an asset like `MS_Secondary_ApocaBloom`.

## The UE4 `.pak` format (version 11), step by step

A `.pak` is Unreal Engine's archive: a mount point, all the file **data** concatenated, and
an **index** at the end that says where each file lives. DRG's is v11, **Zlib**-compressed,
**unencrypted**.

### 1. The footer (last 256 bytes)

Read the last 256 bytes and find the magic `0x5A6F12E1` (bytes `E1 12 6F 5A`). Right after it:

```
magic (4) │ version (4) │ IndexOffset (int64) │ IndexSize (int64) │ IndexHash (20) │ …
```

The byte just *before* the magic is `bEncryptedIndex` (0 for DRG). `version == 11` tells us
the index uses the "path-hash + full-directory" layout below.

### 2. The primary index (at `IndexOffset`)

Serialized in order:

```
FString  MountPoint            (e.g. "../../../")
int32    NumEntries
uint64   PathHashSeed
int32    bHasPathHashIndex     → if 1: int64 offset, int64 size, byte[20] hash
int32    bHasFullDirectoryIndex→ if 1: int64 offset, int64 size, byte[20] hash
int32    EncodedPakEntriesSize
byte[]   EncodedPakEntries     ← compact, bit-packed file records (see step 4)
int32    NumFiles              (non-encoded entries; 0 here)
```

An **FString** is `int32 length` then that many bytes (`length > 0` = ASCII incl. the
trailing `\0`; `length < 0` = UTF-16, `-length` chars).

### 3. The full directory index (at its offset)

A map of directory → (filename → offset into `EncodedPakEntries`):

```
int32 NumDirectories
  repeat: FString DirName
          int32 NumFiles
            repeat: FString FileName
                    int32 EncodedEntryOffset
```

Concatenating `DirName + FileName` gives paths like
`FSD/Content/GameElements/KPI/MissionStats/MS_Secondary_ApocaBloom.uexp`. We keep the ones
under `.../MissionStats/MS_*`.

### 4. Decoding one file record (the bit-packed entry)

At `EncodedEntryOffset` inside `EncodedPakEntries`, a `uint32` flags word packs everything:

| bits | meaning |
|---|---|
| 31 | offset is 32-bit (else 64-bit) |
| 30 | uncompressed size is 32-bit (else 64-bit) |
| 29 | compressed size is 32-bit (else 64-bit) |
| 23–28 | compression method index (0 = stored, else index into the footer's method list → Zlib) |
| 22 | encrypted |
| 6–21 | compression block count |
| 0–5 | block size >> 11 |

We only need the **data offset** and **compressed size**, so we read the flags, then the
offset, uncompressed size, and (if compressed) the compressed size. That's all `entry_loc()`
does.

### 5. Getting the bytes out

Seek to the data offset, read `compressed_size + a little`. If the method index is 0 the
data is stored raw; otherwise it's a single **Zlib** block, so we find the Zlib header
(`0x78 0x9C/0x01/0xDA`) and `zlib.decompress` it. These MS_ assets are tiny (a few KB) → one
block, no multi-block bookkeeping needed.

## Linking a name to its GUID — the answer-key trick

An asset's bytes contain several 16-byte values (its own GUID, references, struct-field
GUIDs). Which one is *the stat's* GUID? We don't parse the asset structure at all. Instead:

1. From the **save**, collect all 95 true stat GUIDs (see the alignment gotcha below).
2. For each `MS_*` asset, slide a 16-byte window over its bytes; the first chunk that is
   **also in the save's set** is the stat's GUID.

Two independent sources agreeing = no guessing. Validation: `MS_Completed_TotalMissions`
resolves to the GUID whose save value is 455 (which is exactly "Missions Completed" in-game).

### ⚠️ The GUID alignment gotcha (save side)

In the save, each stat entry ends with the `Value` float property. The stat's true 16-byte
GUID is the bytes **ending 4 bytes before** the FString `"Value"` — i.e. `data[v-20:v-4]`
where `v` is the index of `b"Value\x00"`. The 4 trailing bytes (`06 00 00 00`) are the
**int32 length prefix of "Value"** (6 = 5 letters + `\0`), *not* part of the GUID. Anchoring
on `data[v-16:v]` makes every GUID look like it ends in `06000000` — a false pattern that
cost us real time.

## Output

`mission_stats.json` — `{ "guid": {"category": ..., "label": ...} }` for all 95 stats. The
category (Overview, Biome, Class, Hazard, Secondary, Warning, Mission Type, Economy, Forging,
Progression, Misc) and the display label come from the curated `CURATED` table in the script,
which uses the exact wording the game's stats screen shows.

Re-run any time (`python tools/extract_mission_stats.py`) to rebuild from scratch.

---
---

# 🇧🇷 Lendo o `.pak` do DRG em Python puro

Esta ferramenta recupera o **nome de cada estatística de missão** lendo o próprio arquivo do
jogo (`FSD-WindowsNoEditor.pak`) e gera o `mission_stats.json`. Usa **só a biblioteca padrão
do Python** (`zlib`, `struct`) — sem descompactador externo.

O *porquê* e a explicação didática (do zero) estão no [`docs/logica.md` §11](../docs/logica.md).
Este arquivo é o *como*: o passo a passo, byte a byte, do formato do pak — pra quando você
quiser entender ou mexer no código.

## O problema em uma linha

O save guarda cada stat como `GUID → número`, nunca o nome. Casar nome por número falha
quando stats compartilham o número (três stats = 41). Então lemos os nomes dos arquivos do
jogo, onde cada stat é um asset tipo `MS_Secondary_ApocaBloom`.

## O formato `.pak` do UE4 (versão 11), por etapas

Um `.pak` é o arquivão da Unreal Engine: um ponto de montagem, os **dados** de todos os
arquivos colados, e um **índice** no fim dizendo onde cada arquivo mora. O do DRG é v11,
comprimido com **Zlib**, **sem criptografia**.

1. **Rodapé (últimos 256 bytes):** ache o magic `0x5A6F12E1`. Logo após:
   `versão (4) │ IndexOffset (int64) │ IndexSize (int64) │ hash (20)`. O byte antes do magic
   é `bEncryptedIndex` (0 no DRG). `versão == 11` = índice no formato "path-hash + diretório
   completo".
2. **Índice primário (em `IndexOffset`):** `FString MountPoint`, `int32 NumEntries`,
   `uint64 PathHashSeed`, flags + offsets do path-hash e do **full directory index**, e o
   blob `EncodedPakEntries` (registros compactos). Uma **FString** é `int32 tamanho` + bytes
   (positivo = ASCII com o `\0`; negativo = UTF-16).
3. **Full directory index:** `int32 nº de diretórios`, e pra cada um: nome, `nº de arquivos`,
   e pra cada arquivo: nome + `int32 offset` no `EncodedPakEntries`. Juntando dir+arquivo dá
   os caminhos `.../MissionStats/MS_*.uexp` — guardamos esses.
4. **Registro de um arquivo (bit-packed):** um `uint32` de flags empacota tudo (offset 32/64
   bits, tamanho, índice do método de compressão nos bits 23–28, contagem de blocos…). Só
   precisamos do **offset dos dados** e do **tamanho comprimido** — é o que `entry_loc()` lê.
5. **Tirar os bytes:** vai no offset, lê `tamanho + folga`. Método 0 = dado cru; senão é um
   bloco **Zlib** único (acha o cabeçalho `0x78 …` e `zlib.decompress`). Os assets `MS_` são
   minúsculos → um bloco só, sem complicação.

## Ligando nome ao GUID — o truque do gabarito

O asset tem vários valores de 16 bytes. Qual é *o GUID da stat*? Não parseamos a estrutura.
Em vez disso: (1) do **save**, pegamos os 95 GUIDs verdadeiros; (2) pra cada asset, deslizamos
uma janela de 16 bytes e o primeiro pedaço que **também está no conjunto do save** é o GUID.
Duas fontes independentes concordando = zero chute. Validação: `MS_Completed_TotalMissions` →
o GUID cujo valor no save é 455 (exatamente "Missions Completed" no jogo).

### ⚠️ A pegadinha do alinhamento (lado do save)

O GUID verdadeiro são os 16 bytes que **terminam 4 bytes ANTES** da FString `"Value"` —
`data[v-20:v-4]`. Os 4 bytes finais (`06 00 00 00`) são o **prefixo de tamanho (int32=6)** de
"Value", não parte do GUID. Ancorar em `data[v-16:v]` faz todo GUID "terminar em 06000000" —
um padrão falso que custou tempo.

## Saída

`mission_stats.json` — `{ "guid": {"category", "label"} }` das 95 stats. Categoria e label
vêm da tabela `CURATED` no script, com o texto exato que a tela de stats do jogo mostra.
Re-rode quando quiser (`python tools/extract_mission_stats.py`) pra reconstruir do zero.
