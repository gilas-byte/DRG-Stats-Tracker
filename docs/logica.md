# 🧠 The reverse-engineering logic (explained to a drunk dwarf)

> 🇬🇧 **English** below · 🇧🇷 **Português** [further down](#-a-lógica-da-engenharia-reversa-explicada-pra-um-anão-bêbado)

---

This file explains, **from absolute zero**, how `drg_save_parser.py` manages to read a Deep
Rock Galactic save file and turn that pile of binary junk into numbers that make sense
(kills, credits, overclocks...).

You don't need to know how to program. If you understand what a number is, you'll
understand this. I go from the dumbest possible concept all the way to the real code. Grab
the wall and come along.

## 0. The idea that solves EVERYTHING

> **A computer file is just a giant queue of numbers from 0 to 255.**

That's it. No magic. A photo, a song, a game save — it's all one long queue of little
numbers (called **bytes**). The DRG save has ~1.4 million of them.

"Reading a binary format" = figuring out **what each chunk of that queue means.** It's like
getting a letter written in an alien language and decoding it letter by letter until you
work out the rules. That's **reverse engineering**: nobody gave you the manual, you figure
it out the hard way.

Here's a mental image to hold on to for the rest of the explanation:

```
The file:    [71][86][65][83][ 8][ 0][ 0][ 0][67][114]... (goes on for 1.4 million)
                ^
                └── a "finger" (a cursor) starts here and walks to the right,
                    reading chunks and "spending" bytes as it understands each thing.
```

Keep that image of the **finger walking along a ruler**. Almost the entire parser is that:
a finger (called `pos` in the code) that walks right, reads a bunch of bytes, understands,
and moves further along. If it miscounts by 1 byte, **everything after it turns to garbage**
— that's why the code is so fussy about "how many bytes each thing spends".

## 1. Byte, and the "backwards number" trick (little-endian)

A **byte** goes from 0 to 255. But big numbers (like 75,466 kills) don't fit in one byte.
So the computer uses **several bytes together** to form a bigger number.

The cruel detail: it stores the bytes **backwards**. That's called **little-endian**.
Example with the number **75,466**:

```
75,466 in bytes (little-endian):   CA 26 01 00
                                    │  │  │  └─ the "heaviest" (worth ×16 million)
                                    │  │  └──── worth ×65,536
                                    │  └─────── worth ×256
                                    └────────── the "lightest" (worth ×1)

Math: 202 + (38 × 256) + (1 × 65,536) = 75,466  ✔
(202 is CA in decimal, 38 is 26, etc. — that's hexadecimal, but ignore that for now.)
```

In the code, the one doing that magic of "take 4 bytes backwards and turn them into a
number" is `struct.unpack_from("<i", data, pos)`:
- the `<` means "little-endian" (backwards),
- the `i` means "4-byte integer".

Every time you see `struct.unpack_from` in the code, that's all it is: **"grab N bytes from
the finger and give me the number they form".**

## 2. The file's badge: "GVAS"

The **first 4 bytes** of the save are the letters `G`, `V`, `A`, `S`. That's a "magic
number" — a badge that says "I'm an Unreal Engine save". The code checks this right at the
start:

```python
if data[:4] != b"GVAS":
    raise ValueError("Não parece um save GVAS válido...")
```

If the first 4 bytes aren't GVAS, the program won't even try — better to fail immediately
than to read garbage. It's the equivalent of checking that the letter came in the right
envelope before opening it.

## 3. Text in the save: the "FString" (the length comes first)

Here's where the clever bit begins. How does the save store a word, like `Credits`?

It does **not** dump the letters loose. It uses a format called **FString**, which looks
like this:

```
[how many letters (4 bytes)] [the letters] [a zero \0 at the end]
```

Example for the word `Credits`:

```
08 00 00 00   C  r  e  d  i  t  s  \0
└─ the number 8 ┘  └──── the 7 letters ───┘ └ trailing zero
   (7 letters + the \0 = 8)
```

So: **before reading the letters, the computer already tells you how many there will be.**
That's smart: the "finger" reads the 8, knows it needs to walk 8 slots, reads the letters,
and stops in exactly the right place. No guessing.

In the code, the one reading an FString is `read_fstring`. It returns TWO things: the text
**and the finger's new position** (`return s, pos + length`). Notice that **every** read
function returns "where the finger stopped" — that's how the finger keeps walking correctly.

```python
def read_fstring(data, pos):
    length = struct.unpack_from("<i", data, pos)[0]   # read the 4 length bytes
    pos += 4                                           # finger walks 4 slots
    s = data[pos:pos + length - 1].decode("ascii")     # read the letters (minus the \0)
    return s, pos + length                             # return text + new finger
```

## 4. How a "property" is built (Name, Type, Size, Data)

The save is a **sequence of properties**, one after another. Each property is like a row in
a spreadsheet, and it **always** comes in this order:

```
[FString Name]  [FString Type]  [int64 Size]  [the data itself]
```

Translated to human, a property says: *"My name is `Credits`, I'm of type `IntProperty` (a
whole number), my data takes 4 bytes, and the value is 142761."*

Knowing this, reading a number becomes mechanical. That's what `read_scalar` does — watch
the finger (`pos`) walking step by step:

```python
def read_scalar(data, name):
    i = find_property(data, name)     # 1. find WHERE this property starts (see §5)
    pos = i
    _, pos      = read_fstring(data, pos)   # 2. skip the Name  (finger walks)
    ptype, pos  = read_fstring(data, pos)   # 3. read the Type  (finger walks)
    pos += 8                                 # 4. skip the Size  (int64 = 8 bytes)
    pos += 1                                 # 5. skip 1 "flag" byte
    # 6. now the finger is EXACTLY on top of the value:
    if ptype == "IntProperty":
        return (ptype, struct.unpack_from("<i", data, pos)[0])   # read 4 bytes = the number
```

See? It's just **walking the finger along the ruler in the right order** and, at the end,
reading the number. If you forget to skip that "1 flag byte", you read everything wrong.
Reverse engineering is 90% figuring out these "skip X bytes here".

## 5. THE MOST IMPORTANT TRAP: finding the right property

How does the finger know **where** `Credits` starts among 1.4 million bytes? The temptation
is: "search for the word `Credits` in the file". **WRONG.** And here lies the most valuable
lesson of the whole project.

If you search for the raw word `Level`, you match inside `RetiredCharacterLevels`,
`LevelUpNotification`, and a whole bunch more — because `Level` appears **inside** those
other words. You'd find the wrong place and read garbage.

**The insight:** remember that text in the save is an FString, with the **length up front**
(§3)? So instead of searching for `Level`, we search for the **exact encoding**:
`[length][Level][\0]`. That way it only matches a REAL property named exactly "Level", never
a piece of another word.

```python
def find_property_encoded(name):
    # build the bytes: [4-byte length] + [the word] + [\0]
    return struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"

def find_property(data, name):
    return data.find(find_property_encoded(name))   # search for the COMPLETE encoding
```

Moral of the story (applies to life): **when you search in binary data, search for the
exact pattern, not the little piece.** A loose substring in binary is a trap.

## 6. The kills dictionary: the `MapProperty` (GUID → count)

Kills aren't a loose number — they're a **dictionary**: "of this creature here, you killed
this many". In the save that's a `MapProperty`. The layout, after the normal header, is:

```
[key type] [value type] [flag] [how many to remove=0] [HOW MANY entries]
and then, repeating N times:  [16-byte key]  [4-byte value]
```

Each creature's key is a **GUID**: a unique **16-byte** code (like the enemy's ID card). The
value is how many you killed. `parse_guid_map` reads the "how many entries" and then runs a
loop, walking the finger **16 bytes (GUID) + 4 bytes (number)** at a time:

```python
num_entries = struct.unpack_from("<i", data, pos)[0]   # e.g. 77 species
pos += 4
for _ in range(num_entries):
    guid = data[pos:pos + 16].hex()      # 16 bytes = the creature's "ID card"
    pos += 16
    v = struct.unpack_from("<i", data, pos)[0]   # 4 bytes = how many you killed
    pos += 4
    out[guid] = v
```

The result is `{ "e977bf0a...": 75466, ... }`. So: we know HOW MANY of EACH creature, but
only by its code. **The creature's name is not in the save.** That leads to the next trick.

## 7. "But how did you discover each creature's NAME?" (the detective method)

The save gives you `GUID → number`. The **name** lives in the game's files, not in the save.
So how do you link `e977bf0a...` to "Glyphid Grunt"? With detective work:

1. In the game, the bestiary shows **name → how many you killed** (e.g. "Glyphid Grunt: 75,466").
2. The save gave us **GUID → how many you killed** (e.g. "e977bf0a...: 75,466").
3. **The kill count is the "glue"!** If the bestiary says Grunt = 75,466, and the save says
   the GUID `e977bf0a...` = 75,466, then that GUID **is** the Grunt. 🎯

That's literally a **JOIN** (joining two tables by a shared column — here, the "kill count"
column). That's how `all_drg_enemies.json` (and `guids.json`) were built. Where two
creatures had the SAME kill count, it became ambiguous — and those uncertainties are noted
in the project, honestly.

Lesson: **when a piece is missing (the name), look for something that both sides HAVE in
common (the number) and use it as a bridge.**

## 8. The numbers the save does NOT store (the "derived" ones)

Not everything is stored ready-made. Some things the game **computes on the fly**. Falling
into this trap cost a real bug:

- **Account rank** (the big number, e.g. 118): NOT stored. The game sums all classes' levels
  and divides by 3. The code redoes that math in `parse_save`.
- **A class's level** (1 to 25): NOT stored — it's derived from **XP**. The `level_from_xp`
  function compares your XP against a table (`CLASS_XP_TABLE`) and finds the level.
- **Promotions**: the save stores it per class, in a field the engine calls `TimesRetired`
  ("retiring" = promoting, in DRG's vocabulary). `parse_classes` reads the 4 class blocks
  and sums.

Each class is a "block" that starts with the **class GUID** (16 fixed bytes, the same in
every save) followed by `XP → TimesRetired → RetiredCharacterLevels`. The code finds the
block by searching for the `XP` property and confirming that a `TimesRetired` shows up right
after (so it doesn't confuse it with some other `XP`).

Lesson: **be careful not to read a "similar" number thinking it's the one you want.** Always
confirm against a value you KNOW is true (here, we matched the computed rank against the rank
shown in-game: they matched → correct).

## 9. The "anchor" trick to find something inside a nasty structure

Sometimes the data is buried in a horrible structure (struct inside struct inside array).
Decoding all of it would be a huge amount of work. So we use a shortcut: **anchor on a
landmark word and read what's around it.**

That's what we did for "missions completed" (`parse_mission_stat`). Each mission statistic
lives near the word `MissionStatID`. So the code:

1. searches for **each** occurrence of `MissionStatID` (the anchor);
2. the statistic's GUID is the 16 bytes right **before** the word `Value`;
3. the number is the `FloatProperty` right **after**;
4. if the GUID matches the one we want, **sum**.

```python
while True:
    i = data.find(b"MissionStatID", pos)   # find the next anchor
    if i < 0: break
    v = data.find(b"Value\x00", i)          # the "Value" just ahead
    if data[v - 16:v] == alvo:              # the 16 bytes before it = the stat's GUID
        # ...read the float right after and sum...
```

Since each statistic is stored **per class** (4 values), we **sum the 4** to match the total
the game shows (127 + 70 + 114 + 134 = **445 missions** ✔). That's exactly how we discovered
that "missions completed" (445) is different from "games played" (504).

Lesson: **you don't need to understand the WHOLE structure. Sometimes a reliable landmark
near the data you want is enough.**

## 10. Overclocks: a list of GUIDs (`parse_guid_array`)

Forged overclocks are a **list** of GUIDs (`ForgedSchematics`). It's an `ArrayProperty`: it
has a header, a "how many items", a little struct header that appears **once**, and then the
GUIDs packed together (16 bytes each). `parse_guid_array` skips the header and reads the
GUIDs in a row. Then we cross-reference with `guids.json` (which maps GUID → overclock name
and weapon) and figure out "you have 100 of 160". Same detective pattern as §7.

## 11. Reading the game's OWN files (the `.pak`) — when the JOIN isn't enough

The trick from §7 (discover names by matching numbers) has a ceiling. Deep Rock tracks
**95 mission statistics** (missions per biome, per class, secondary objectives, warnings…),
each stored in the save as a **GUID + a number** — but, again, no names. We tried the same
JOIN: read the number the game shows on its stats screen, find the GUID with that number. It
worked for some. But **lots of stats share the same number** — three different ones all
equalled 41. When two things have the same number, matching by number CAN'T tell them apart
(the same wall as the twin creatures in §7). Dead end.

So we stopped squeezing the save and went to the source: **the game's own files.**

**What's a `.pak`?** A game doesn't ship thousands of loose files — it squishes all its art,
sounds and data into one giant archive, like a ZIP. DRG's is `FSD-WindowsNoEditor.pak`,
**2.4 GB**. Inside, each statistic is a tiny file with a **clear name** — the "Apoca Bloom"
secondary is a file literally called `MS_Secondary_ApocaBloom`. The names we wanted are right
there; we just have to crack the archive open.

Two hurdles, and how we cleared them:

1. **The files inside are compressed** (squished to save space). Here we got lucky: this pak
   uses **Zlib** compression, and Python un-squishes Zlib for free (the built-in `zlib`). If
   it had used the other common method ("Oodle"), we'd have needed an extra tool. So: pure
   Python, no downloads.
2. **Which 16 bytes in a stat's file is its GUID?** A file has lots of bytes. Here's the
   elegant part: we **use the save as an answer key.** We already pulled all 95 real GUIDs
   from the save. So we open a stat's file, slide over it 16 bytes at a time, and the chunk
   that ALSO shows up in the save's list — that's the GUID. Zero guessing; the two sources
   confirm each other.

**The sneaky bug we squashed along the way.** When reading a GUID from the save, the *true*
16 bytes end **4 bytes before** the word `Value` that follows. Those 4 bytes (`06 00 00 00`)
were actually the **length of the word "Value"** (5 letters + the hidden `\0` = 6), not part
of the GUID. Grabbing the wrong 16 bytes made **every** GUID look like it ended in
`06000000` — a classic "off by 4" that sent us chasing a fake pattern for a while. The rule:
count your bytes twice (§0's finger is unforgiving).

**The payoff:** all **95 stats** mapped with zero ambiguity, written into `mission_stats.json`
(GUID → name + category) by `tools/extract_mission_stats.py`. And a bonus truth fell out:
someone asked for "Cargo Crates" and "Lost Equipment" stats — but there's **no such file** in
the pak and the game's stats screen never shows them. They simply **aren't tracked**. That's
not a failure of our tool; it's a real, provable answer — sometimes the honest result is
"the data doesn't exist."

## 12. The general method (how to reverse-engineer things yourself)

If one day you want to decode ANOTHER format from scratch, the recipe is:

1. **Search for something you ALREADY KNOW.** You know you have 75,466 Grunt kills? Convert
   75,466 to bytes (`CA 26 01 00`) and search for that sequence in the file. Found it? Then
   you discovered WHERE the count lives — and the GUID is probably right before it.
2. **Find the repeating pattern.** If every entry is "16 bytes + 4 bytes", you found the
   dictionary's rule.
3. **Form a hypothesis and TEST it against reality.** "I think this number is the rank."
   Compute it and compare with what the game shows. Matched? Good hypothesis. Didn't? Discard.
4. **Distrust coincidences.** A substring matching by chance (§5), two creatures with the
   same count (§7), a "similar" number that isn't the right one (§8). Always validate.
5. **Write everything down.** Every byte you decode is gold — write it down so you don't
   rediscover it. (That's why this project has `logica.md` and `claude_public.md`.)

## TL;DR (the 5-line version)

- A save is **a queue of numbers**. A "finger" (`pos`) walks along it reading chunks.
- **Text has its length up front** (FString) — that's why the finger never gets lost.
- **Find properties by their exact encoding**, never by a loose substring.
- The save gives **codes (GUIDs)**; we discovered the **names** by a JOIN (matching numbers).
- Some numbers are **computed**, not stored — careful not to read the wrong "similar" one.
- When matching by number ties up, **read the game's OWN files** (the `.pak`) and cross-check
  the GUIDs against the save (which acts as an answer key).

Rock and Stone, miner. Now you know how to read bytes. ⛏️

---
---

# 🧠 A lógica da engenharia reversa (explicada pra um anão bêbado)

Este arquivo explica, **do zero absoluto**, como o `drg_save_parser.py` consegue ler um
arquivo de save do Deep Rock Galactic e transformar aquele monte de lixo binário em
números que fazem sentido (kills, créditos, overclocks...).

Não precisa saber programar. Se você entende o que é um número, você entende isto aqui.
Vou do conceito mais burro possível até o código de verdade. Segura na parede e vem.

## 0. A ideia que resolve TUDO

> **Um arquivo de computador é só uma fila gigante de números de 0 a 255.**

É isso. Não tem mágica. Uma foto, uma música, um save de jogo — tudo é uma fila
comprida de numerozinhos (chamados **bytes**). O save do DRG tem ~1,4 milhão desses.

"Ler um formato binário" = descobrir **o que cada pedaço dessa fila significa.** É tipo
receber uma carta escrita num idioma alienígena e ir decifrando letra por letra até
sacar as regras. Isso é **engenharia reversa**: ninguém te deu o manual, você descobre
na marra.

Vou te dar uma imagem mental pra guardar o resto da explicação:

```
O arquivo:   [71][86][65][83][ 8][ 0][ 0][ 0][67][114]... (segue por 1,4 milhão)
                ^
                └── um "dedo" (um cursor) começa aqui e vai andando pra direita,
                    lendo pedaços e "gastando" bytes conforme entende cada coisa.
```

Guarda essa imagem do **dedo andando na régua**. Quase todo o parser é isso: um dedo
(no código chamado `pos`) que anda pra direita, lê um tanto de bytes, entende, e anda
mais pra frente. Se ele contar 1 byte errado, **todo o resto vira lixo** — por isso o
código é tão chato com "quantos bytes cada coisa gasta".

## 1. Byte, e o truque do número "de trás pra frente" (little-endian)

Um **byte** vai de 0 a 255. Mas números grandes (tipo 75.466 kills) não cabem em um
byte. Então o computador usa **vários bytes juntos** pra formar um número maior.

O detalhe cruel: ele guarda os bytes **de trás pra frente**. Isso se chama
**little-endian**. Exemplo com o número **75.466**:

```
75.466 em bytes (little-endian):   CA 26 01 00
                                    │  │  │  └─ mais "pesado" (vale ×16 milhões)
                                    │  │  └──── vale ×65.536
                                    │  └─────── vale ×256
                                    └────────── mais "leve" (vale ×1)

Conta: 202 + (38 × 256) + (1 × 65.536) = 75.466  ✔
(202 é o CA em decimal, 38 é o 26, etc. — é hexadecimal, mas ignora isso por ora.)
```

No código, quem faz essa mágica de "juntar 4 bytes de trás pra frente e virar um número"
é o `struct.unpack_from("<i", data, pos)`:
- o `<` significa "little-endian" (de trás pra frente),
- o `i` significa "número inteiro de 4 bytes".

Toda vez que você vê `struct.unpack_from` no código, é só isso: **"pega N bytes a partir
do dedo e me devolve o número que eles formam".**

## 2. O crachá do arquivo: "GVAS"

Os **4 primeiros bytes** do save são as letras `G`, `V`, `A`, `S`. Isso é uma "magic
number" — um crachá que diz "sou um save da Unreal Engine". O código checa isso logo no
começo:

```python
if data[:4] != b"GVAS":
    raise ValueError("Não parece um save GVAS válido...")
```

Se os 4 primeiros bytes não forem GVAS, o programa nem tenta — melhor falhar na hora do
que ler lixo. É o equivalente a conferir se a carta veio no envelope certo antes de abrir.

## 3. Texto no save: a "FString" (o tamanho vem na frente)

Aqui começa o pulo do gato. Como o save guarda uma palavra, tipo `Credits`?

Ele **não** joga as letras soltas. Ele usa um formato chamado **FString**, que é assim:

```
[quantas letras (4 bytes)] [as letras] [um zero \0 no fim]
```

Exemplo pra palavra `Credits`:

```
08 00 00 00   C  r  e  d  i  t  s  \0
└─ o número 8 ─┘  └──── as 7 letras ───┘ └ zero final
   (7 letras + o \0 = 8)
```

Ou seja: **antes de ler as letras, o computador já te avisa quantas vão ser.** Isso é
esperto: o "dedo" lê o 8, sabe que precisa andar 8 casas, lê as letras, e para exatamente
no lugar certo. Sem adivinhação.

No código, quem lê uma FString é a `read_fstring`. Ela devolve DUAS coisas: o texto **e a
nova posição do dedo** (`return s, pos + length`). Repara que **toda** função de leitura
devolve "onde o dedo parou" — é assim que o dedo continua andando certo.

```python
def read_fstring(data, pos):
    length = struct.unpack_from("<i", data, pos)[0]   # lê os 4 bytes do tamanho
    pos += 4                                           # dedo anda 4 casas
    s = data[pos:pos + length - 1].decode("ascii")     # lê as letras (menos o \0)
    return s, pos + length                             # devolve texto + dedo novo
```

## 4. Como uma "propriedade" é montada (Nome, Tipo, Tamanho, Dado)

O save é uma **sequência de propriedades**, uma atrás da outra. Cada propriedade é tipo
uma linha de uma planilha, e vem **sempre nesta ordem**:

```
[FString Nome]  [FString Tipo]  [int64 Tamanho]  [o dado em si]
```

Traduzindo pra humano, uma propriedade diz: *"Meu nome é `Credits`, eu sou do tipo
`IntProperty` (um número inteiro), meu dado ocupa 4 bytes, e o valor é 142761."*

Sabendo isso, ler um número vira mecânico. É o que a `read_scalar` faz — repara o dedo
(`pos`) andando passo a passo:

```python
def read_scalar(data, name):
    i = find_property(data, name)     # 1. acha ONDE essa propriedade começa (ver §5)
    pos = i
    _, pos      = read_fstring(data, pos)   # 2. pula o Nome  (dedo anda)
    ptype, pos  = read_fstring(data, pos)   # 3. lê o Tipo    (dedo anda)
    pos += 8                                 # 4. pula o Tamanho (int64 = 8 bytes)
    pos += 1                                 # 5. pula 1 byte de "flag"
    # 6. agora o dedo está EXATAMENTE em cima do valor:
    if ptype == "IntProperty":
        return (ptype, struct.unpack_from("<i", data, pos)[0])   # lê 4 bytes = o número
```

Viu? É só **andar o dedo na régua na ordem certa** e, no fim, ler o número. Se você
esquecer de pular aquele "1 byte de flag", lê tudo torto. Engenharia reversa é 90%
descobrir esses "pula X bytes aqui".

## 5. A ARMADILHA MAIS IMPORTANTE: achar a propriedade certa

Como o dedo sabe **onde** `Credits` começa no meio de 1,4 milhão de bytes? A tentação é:
"procura a palavra `Credits` no arquivo". **ERRADO.** E aqui mora a lição mais valiosa
de todo o projeto.

Se você procurar a palavra crua `Level`, você casa dentro de `RetiredCharacterLevels`,
`LevelUpNotification`, e mais um monte — porque `Level` aparece **dentro** dessas outras
palavras. Você acharia o lugar errado e leria lixo.

**A sacada:** lembra que texto no save é uma FString, com o **tamanho na frente** (§3)?
Então em vez de procurar `Level`, a gente procura a **codificação exata**:
`[tamanho][Level][\0]`. Assim só casa com uma propriedade DE VERDADE chamada exatamente
"Level", nunca com um pedaço de outra palavra.

```python
def find_property_encoded(name):
    # monta os bytes: [tamanho de 4 bytes] + [a palavra] + [\0]
    return struct.pack("<i", len(name) + 1) + name.encode() + b"\x00"

def find_property(data, name):
    return data.find(find_property_encoded(name))   # procura a codificação COMPLETA
```

Moral da história (vale pra vida): **quando você busca em dados binários, busque o
padrão exato, não o pedacinho.** Substring solta em binário é cilada.

## 6. O dicionário de kills: o `MapProperty` (GUID → contagem)

As kills não são um número solto — são um **dicionário**: "desse bicho aqui, você matou
tanto". No save isso é um `MapProperty`. O layout, depois do cabeçalho normal, é:

```
[Tipo da chave] [Tipo do valor] [flag] [quantos remover=0] [QUANTAS entradas]
e aí, repetindo N vezes:  [chave de 16 bytes]  [valor de 4 bytes]
```

A chave de cada bicho é um **GUID**: um código único de **16 bytes** (tipo o RG do
inimigo). O valor é quantos você matou. A `parse_guid_map` lê o "quantas entradas" e
então roda um laço, andando o dedo **16 bytes (GUID) + 4 bytes (número)** por vez:

```python
num_entries = struct.unpack_from("<i", data, pos)[0]   # ex.: 77 espécies
pos += 4
for _ in range(num_entries):
    guid = data[pos:pos + 16].hex()      # 16 bytes = o "RG" do bicho
    pos += 16
    v = struct.unpack_from("<i", data, pos)[0]   # 4 bytes = quantos você matou
    pos += 4
    out[guid] = v
```

O resultado é `{ "e977bf0a...": 75466, ... }`. Ou seja: sabemos QUANTO de CADA bicho,
mas só pelo código dele. **O nome do bicho não está no save.** Isso leva ao próximo truque.

## 7. "Mas como vocês descobriram o NOME de cada bicho?" (o método detetive)

O save te dá `GUID → número`. O **nome** mora nos arquivos do jogo, não no save. Então
como ligar `e977bf0a...` ao "Glyphid Grunt"? Com trabalho de detetive:

1. No jogo, o bestiário mostra **nome → quantos você matou** (ex.: "Glyphid Grunt: 75.466").
2. O save nos deu **GUID → quantos você matou** (ex.: "e977bf0a...: 75.466").
3. **O número de kills é a "cola"!** Se o bestiário diz que Grunt = 75.466, e o save diz
   que o GUID `e977bf0a...` = 75.466, então esse GUID **é** o Grunt. 🎯

Isso é literalmente um **JOIN** (juntar duas tabelas por uma coluna em comum — aqui, a
coluna "número de kills"). Foi assim que o `all_drg_enemies.json` (e o `guids.json`) foram
montados. Onde dois bichos tinham o MESMO número de kills, aí ficou ambíguo — e essas
incertezas estão anotadas no projeto, honestamente.

Lição: **quando falta uma peça (o nome), procure outra coisa que os dois lados TÊM em
comum (o número) e use como ponte.**

## 8. Os números que o save NÃO guarda (os "derivados")

Nem tudo está salvo pronto. Algumas coisas o jogo **calcula na hora**. Cair nessa
armadilha custou um bug real:

- **Rank da conta** (o número grande, ex.: 118): NÃO está salvo. O jogo soma os levels de
  todas as classes e divide por 3. O código refaz essa conta em `parse_save`.
- **Level de uma classe** (1 a 25): NÃO está salvo — é derivado do **XP**. A função
  `level_from_xp` compara seu XP com uma tabela (`CLASS_XP_TABLE`) e descobre o level.
- **Promoções**: o save guarda por classe, num campo que a engine chama `TimesRetired`
  ("aposentar" = promover, no vocabulário do DRG). A `parse_classes` lê os 4 blocos de
  classe e soma.

Cada classe é um "bloco" que começa com o **GUID da classe** (16 bytes fixos, iguais em
todo save) seguido de `XP → TimesRetired → RetiredCharacterLevels`. O código acha o bloco
procurando a propriedade `XP` e confirmando que um `TimesRetired` aparece logo depois
(pra não confundir com outro `XP` qualquer).

Lição: **cuidado pra não ler um número "parecido" achando que é o que você quer.** Sempre
confirme contra um valor que você SABE que é verdade (aqui, batemos o rank calculado com
o rank que aparece no jogo: deu igual → tá certo).

## 9. O truque da "âncora" pra achar coisa dentro de estrutura complicada

Às vezes o dado está enterrado numa estrutura horrível (struct dentro de struct dentro de
array). Decodificar tudo daria um trabalho enorme. Aí usamos um atalho: **ancorar numa
palavra-marco e ler o que está ao redor dela.**

Foi assim com as "missões concluídas" (`parse_mission_stat`). Cada estatística de missão
vive perto da palavra `MissionStatID`. Então o código:

1. procura **cada** aparição de `MissionStatID` (a âncora);
2. o GUID da estatística são os 16 bytes logo **antes** da palavra `Value`;
3. o número é o `FloatProperty` logo **depois**;
4. se o GUID bate com o que a gente quer, **soma**.

```python
while True:
    i = data.find(b"MissionStatID", pos)   # acha a próxima âncora
    if i < 0: break
    v = data.find(b"Value\x00", i)          # o "Value" logo à frente
    if data[v - 16:v] == alvo:              # os 16 bytes antes = o GUID da stat
        # ...lê o float logo depois e soma...
```

Como cada estatística é guardada **por classe** (4 valores), a gente **soma os 4** pra
bater com o total que o jogo mostra (127 + 70 + 114 + 134 = **445 missões** ✔). Foi
exatamente assim que descobrimos que "missões concluídas" (445) é diferente de "partidas
jogadas" (504).

Lição: **você não precisa entender a estrutura INTEIRA. Às vezes basta uma marca
confiável perto do dado que você quer.**

## 10. Overclocks: lista de GUIDs (o `parse_guid_array`)

Overclocks forjados são uma **lista** de GUIDs (`ForgedSchematics`). É um `ArrayProperty`:
tem um cabeçalho, um "quantos itens", um cabecinho de struct que aparece **uma vez**, e aí
os GUIDs coladinhos (16 bytes cada). A `parse_guid_array` pula o cabeçalho e lê os GUIDs
em fila. Depois a gente cruza com o `guids.json` (que mapeia GUID → nome do overclock e
arma) e descobre "você tem 100 de 160". Mesmo padrão de detetive do §7.

## 11. Lendo os PRÓPRIOS arquivos do jogo (o `.pak`) — quando o JOIN não basta

O truque do §7 (descobrir nomes batendo números) tem um teto. O Deep Rock guarda **95
estatísticas de missão** (missões por bioma, por classe, objetivos secundários, warnings…),
cada uma salva como **GUID + um número** — mas, de novo, sem nome. Tentamos o mesmo JOIN: ler
o número que o jogo mostra na tela de stats, achar o GUID com aquele número. Funcionou pra
algumas. Só que **muitas stats têm o MESMO número** — três diferentes valiam 41. Quando duas
coisas têm o mesmo número, casar por número NÃO consegue distinguir (a mesma parede dos bichos
gêmeos do §7). Beco sem saída.

Então paramos de espremer o save e fomos na fonte: **os próprios arquivos do jogo.**

**O que é um `.pak`?** Um jogo não vem com milhares de arquivos soltos — ele espreme toda a
arte, som e dados num arquivão só, tipo um ZIP. O do DRG é o `FSD-WindowsNoEditor.pak`, de
**2.4 GB**. Lá dentro, cada estatística é um arquivinho com **nome claro** — a secundária de
"Apoca Bloom" é um arquivo chamado literalmente `MS_Secondary_ApocaBloom`. Os nomes que a
gente queria estão ali; é só arrombar o arquivão.

Dois obstáculos, e como passamos:

1. **Os arquivos lá dentro estão comprimidos** (espremidos pra ocupar menos). Aqui deu sorte:
   este pak usa compressão **Zlib**, e o Python descomprime Zlib de graça (o módulo embutido
   `zlib`). Se fosse o outro método comum ("Oodle"), precisaríamos de uma ferramenta extra.
   Então: Python puro, sem baixar nada.
2. **Quais 16 bytes do arquivo de uma stat são o GUID dela?** Um arquivo tem um monte de
   bytes. Aqui está a parte elegante: usamos o **save como gabarito.** A gente já tinha os 95
   GUIDs verdadeiros tirados do save. Então abrimos o arquivo de uma stat, deslizamos de 16
   em 16 bytes, e o pedaço que TAMBÉM aparece na lista do save — esse é o GUID. Zero chute; as
   duas fontes se confirmam.

**O bug sacana que esmagamos no caminho.** Ao ler um GUID do save, os 16 bytes *verdadeiros*
terminam **4 bytes ANTES** da palavra `Value` que vem logo depois. Esses 4 bytes
(`06 00 00 00`) eram na verdade o **tamanho da palavra "Value"** (5 letras + o `\0` escondido
= 6), não parte do GUID. Pegar os 16 bytes errados fazia **TODO** GUID parecer terminar em
`06000000` — um clássico "errou por 4" que nos fez perseguir um padrão falso por um tempo. A
regra: conte seus bytes duas vezes (o dedo do §0 não perdoa).

**O prêmio:** as **95 stats** mapeadas com zero ambiguidade, gravadas no `mission_stats.json`
(GUID → nome + categoria) pelo `tools/extract_mission_stats.py`. E uma verdade-bônus caiu no
colo: alguém pediu as stats de "Cargo Crates" e "Lost Equipment" — mas **não existe arquivo
desses** no pak e a tela de stats do jogo nunca os mostra. Simplesmente **não são
rastreados**. Isso não é falha da ferramenta; é uma resposta real e demonstrável — às vezes o
resultado honesto é "esse dado não existe".

## 12. O método geral (como fazer engenharia reversa você mesmo)

Se um dia você quiser decifrar OUTRO formato do zero, a receita é:

1. **Procure algo que você JÁ SABE.** Você sabe que tem 75.466 kills de Grunt? Converte
   75.466 pra bytes (`CA 26 01 00`) e procura essa sequência no arquivo. Achou? Então você
   descobriu ONDE fica a contagem — e provavelmente o GUID está logo antes.
2. **Ache o padrão que se repete.** Se toda entrada é "16 bytes + 4 bytes", você achou a
   regra do dicionário.
3. **Levante uma hipótese e TESTE contra a realidade.** "Acho que esse número é o rank."
   Calcula e compara com o que o jogo mostra. Bateu? Hipótese boa. Não bateu? Descarta.
4. **Desconfie de coincidências.** Substring casando por acaso (§5), dois bichos com a
   mesma contagem (§7), um número "parecido" que não é o certo (§8). Sempre valide.
5. **Anote tudo.** Cada byte que você decifrar é ouro — anote pra não redescobrir. (É por
   isso que este projeto tem o `claude_public.md` e este `logica.md`.)

## TL;DR (a versão de 5 linhas)

- Um save é **uma fila de números**. Um "dedo" (`pos`) anda por ela lendo pedaços.
- **Texto tem o tamanho na frente** (FString) — por isso o dedo nunca se perde.
- **Ache propriedades pela codificação exata**, nunca por substring solta.
- O save dá **códigos (GUIDs)**; os **nomes** a gente descobriu por JOIN (batendo números).
- Alguns números são **calculados**, não salvos — cuidado pra não ler o "parecido" errado.
- Quando casar por número empata, **leia os PRÓPRIOS arquivos do jogo** (o `.pak`) e confira
  os GUIDs contra o save (que serve de gabarito).

Rock and Stone, mineiro. Agora você sabe ler bytes. ⛏️
