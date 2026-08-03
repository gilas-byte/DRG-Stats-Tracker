# 🧠 A lógica da engenharia reversa (explicada pra um anão bêbado)

Este arquivo explica, **do zero absoluto**, como o `drg_save_parser.py` consegue ler um
arquivo de save do Deep Rock Galactic e transformar aquele monte de lixo binário em
números que fazem sentido (kills, créditos, overclocks...).

Não precisa saber programar. Se você entende o que é um número, você entende isto aqui.
Vou do conceito mais burro possível até o código de verdade. Segura na parede e vem.

---

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

---

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

---

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

---

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

---

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

---

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

---

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

---

## 7. "Mas como vocês descobriram o NOME de cada bicho?" (o método detetive)

O save te dá `GUID → número`. O **nome** mora nos arquivos do jogo, não no save. Então
como ligar `e977bf0a...` ao "Glyphid Grunt"? Com trabalho de detetive:

1. No jogo, o bestiário mostra **nome → quantos você matou** (ex.: "Glyphid Grunt: 75.466").
2. O save nos deu **GUID → quantos você matou** (ex.: "e977bf0a...: 75.466").
3. **O número de kills é a "cola"!** Se o bestiário diz que Grunt = 75.466, e o save diz
   que o GUID `e977bf0a...` = 75.466, então esse GUID **é** o Grunt. 🎯

Isso é literalmente um **JOIN** (juntar duas tabelas por uma coluna em comum — aqui, a
coluna "número de kills"). Foi assim que o `enemy_names.json` (e o `guids.json`) foram
montados. Onde dois bichos tinham o MESMO número de kills, aí ficou ambíguo — e essas
incertezas estão anotadas no projeto, honestamente.

Lição: **quando falta uma peça (o nome), procure outra coisa que os dois lados TÊM em
comum (o número) e use como ponte.**

---

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

---

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

---

## 10. Overclocks: lista de GUIDs (o `parse_guid_array`)

Overclocks forjados são uma **lista** de GUIDs (`ForgedSchematics`). É um `ArrayProperty`:
tem um cabeçalho, um "quantos itens", um cabecinho de struct que aparece **uma vez**, e aí
os GUIDs coladinhos (16 bytes cada). A `parse_guid_array` pula o cabeçalho e lê os GUIDs
em fila. Depois a gente cruza com o `guids.json` (que mapeia GUID → nome do overclock e
arma) e descobre "você tem 100 de 160". Mesmo padrão de detetive do §7.

---

## 11. O método geral (como fazer engenharia reversa você mesmo)

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
   isso que este projeto tem o `CLAUDE.md` e este `logica.md`.)

---

## TL;DR (a versão de 5 linhas)

- Um save é **uma fila de números**. Um "dedo" (`pos`) anda por ela lendo pedaços.
- **Texto tem o tamanho na frente** (FString) — por isso o dedo nunca se perde.
- **Ache propriedades pela codificação exata**, nunca por substring solta.
- O save dá **códigos (GUIDs)**; os **nomes** a gente descobriu por JOIN (batendo números).
- Alguns números são **calculados**, não salvos — cuidado pra não ler o "parecido" errado.

Rock and Stone, mineiro. Agora você sabe ler bytes. ⛏️
