# DRG Stats Tracker — Guia Técnico do Projeto

> Este arquivo é o **mapa técnico do projeto**: o que existe, como funciona e por quê.
> As seções assumem só o que veio antes; dá pra ler na ordem. Documentação de apoio
> (com explicações mais detalhadas) fica em `README.md` e `logica.md`.

---

## 1. O que é este projeto (visão geral)

O jogo **Deep Rock Galactic** guarda, num arquivo de save, quantos inimigos de cada
espécie você matou na vida (e mais um monte de estatística). O jogo mostra isso só
dentro do bestiário, um bicho por vez, sem histórico e sem gráfico.

**O que a gente está construindo:** um programa que lê esse save, extrai os números,
guarda num banco de dados local a cada vez que roda (formando um **histórico**), e no
fim mostra tudo num **painel com gráficos** (kills por espécie, evolução ao longo do
tempo, etc.).

Por que isso é um bom projeto de portfólio: ele junta as três etapas de um trabalho de
dados de verdade — **extrair** (de um formato binário cru), **armazenar** (modelagem de
banco) e **visualizar** (dashboard). Mostra pra um recrutador que você não tem medo de
meter a mão num formato desconhecido.

---

## 2. Vocabulário mínimo (termos que aparecem no projeto)

Antes dos arquivos, os termos que aparecem o tempo todo:

- **Script / arquivo `.py`**: um arquivo de texto com instruções que o Python executa de cima pra baixo. É a "receita".
- **Variável**: uma caixa com nome que guarda um valor. `x = 5` põe o número 5 na caixa chamada `x`.
- **Função (`def`)**: uma mini-máquina reutilizável. Você dá entradas, ela devolve uma saída. Ex.: `def dobro(n): return n*2`.
- **Lista `[ ]`**: uma fila ordenada de coisas. `[10, 20, 30]`.
- **Dicionário `{ }`**: pares **chave → valor**, igual um dicionário de verdade (procura a palavra, acha a definição). `{"grunt": 75466}`.
- **`import`**: trazer código de outro arquivo pra usar aqui. É como pegar uma ferramenta emprestada de outra caixa.
- **Loop (`for` / `while`)**: repetir uma ação várias vezes.
- **Byte**: a forma mais crua de dado — um número de 0 a 255. **Todo arquivo do computador é só uma sequência gigante de bytes.** Ler um formato "binário" é interpretar essa sequência.
- **Banco de dados / SQLite**: um jeito organizado de guardar dados em **tabelas** (que são tipo planilhas: linhas e colunas). SQLite guarda tudo num único arquivo local, sem servidor.
- **SQL**: a linguagem pra falar com o banco. `SELECT` = pegar dados, `INSERT` = guardar, `JOIN` = juntar duas tabelas por uma coluna em comum.

---

## 3. Como as peças se conectam (arquitetura)

O fluxo dos dados, da esquerda pra direita:

```
  save do jogo            traduz bytes           guarda com histórico        mostra bonito
 (XXXXX_Player.sav)  ->  drg_save_parser.py  ->      snapshot.py        ->    dashboard.py
        │                       │                        │                        │
        │                       │                   drg_stats.db  <──────────────-┘
        │                       │                  (banco SQLite)      (lê o banco)
        │                       │
        └── all_drg_enemies.json ───┘  (traduz o ID interno do bicho -> nome legível)
```

Em palavras: o **parser** sabe ler o save cru. O **snapshot** usa o parser pra tirar uma
"foto" e gravar no **banco**. O **dashboard** lê o banco e desenha os gráficos. O
**all_drg_enemies.json** é a tabelinha que troca os códigos internos pelos nomes dos bichos.

---

## 4. O formato do save (conhecimento técnico que já descobrimos)

Isto aqui é ouro — foi engenharia reversa feita na mão. Guardado pra ninguém precisar
redescobrir.

- O arquivo é do tipo **GVAS** (formato de save da engine Unreal). Os 4 primeiros bytes são as letras `GVAS`.
- Os números são gravados em **little-endian** (do byte menos significativo pro mais significativo — tipo escrever "de trás pra frente"). Ex.: o número 75466 vira os bytes `ca 26 01 00`.
- O save é uma sequência de **propriedades**, cada uma no formato: `[Nome][Tipo][Tamanho][Dados]`.
- **Texto** é guardado como **FString**: primeiro um número de 4 bytes com o tamanho, depois as letras, terminando em `\0`. (Por isso, pra achar uma propriedade, buscamos essa codificação exata, não a palavra solta — senão "Level" casaria dentro de "RetiredCharacterLevels".)
- A propriedade **`EnemiesKilled`** é um **MapProperty** (um dicionário): a chave é um **GUID** de 16 bytes (um ID único do inimigo) e o valor é a contagem de kills (`IntProperty`, 4 bytes). São **77 espécies**.
  - Layout do cabeçalho do mapa: `Nome` → `"MapProperty"` → `Tamanho (int64)` → `"StructProperty"` (tipo da chave) → `"IntProperty"` (tipo do valor) → 1 byte de flag → `int32 remover` → `int32 nº_de_entradas` → depois as entradas (cada uma = 16 bytes de GUID + 4 bytes de contagem).
- **Escalares soltos** (número único): `Credits`, `PerkPoints`, `NumberOfGamesPlayed`, `TotalPlayTimeSeconds`.
- **`OwnedResources`**: outro mapa, GUID → valor `FloatProperty` (recursos que você tem). 22 entradas. (Ainda não usamos no dashboard.)
- Referência confirmada: o GUID `e977bf0a42a9ed46a0d89c8d874adcff` = **Glyphid Grunt** (bateu com a screenshot do jogo).

### 4.1 Rank da conta e promoções (⚠️ NÃO são escalares — são DERIVADOS)

Armadilha grande que já custou um bug: **o "Rank" da conta (o número grande no
jogo, ex.: 115) e o total de promoções NÃO ficam salvos como um número pronto.**
Existe até uma propriedade chamada `Level` no save, mas ela é um "level" solto
qualquer (valeu 44 no teste) — **não** é o rank. Ler `read_scalar("Level")` dá o
número errado. Idem `read_scalar("TimesRetired")`: pega só a 1ª classe.

O que o save realmente guarda é **um bloco por classe** (Driller, Engineer,
Gunner, Scout). Cada bloco é chaveado pelo **GUID da classe** (16 bytes, constante
fixa do jogo) e contém, em ordem: `XP (IntProperty)` → `TimesRetired (IntProperty)`
→ `RetiredCharacterLevels (IntProperty)`. Detalhes:

- **`TimesRetired` por classe = número de PROMOÇÕES daquela classe.** A engine chama
  promoção de "retire". Somando as 4 classes dá o total de promoções (ex.: 1+3+3+3=10).
  (Cuidado: existe um 5º bloco-fantasma com GUID `6e68d5d6…`, XP 0 — ignorar.)
- **Level da classe (1–25) é DERIVADO do XP**, não fica salvo. Usa a tabela de XP
  cumulativo do DRG (`CLASS_XP_TABLE`), que trava em **315000 = level 25** (aí libera
  a promoção). Confirmado: XP 282845→lvl 23, 300779→lvl 24, 315000→lvl 25.
- **Rank da conta** = `(soma dos levels totais das 4 classes) // 3`, onde o "level
  total" de uma classe = `RetiredCharacterLevels + level_atual`. Ex.:
  (25+24)+(75+25)+(75+23)+(75+25) = 49+100+98+100 = 347 → `347//3` = **115**. ✔
- **GUIDs das classes** (confirmados batendo com o bestiário/print):
  Driller `9edd56f1…`, Engineer `85ef626c…`, Gunner `ae56e180…`, Scout `30d8ea17…`.

Isso vive em `parse_classes()` + `level_from_xp()` no parser. O `parse_save`
devolve `player_rank`, `promotions` e a lista `classes` (detalhe por classe). As
chaves `level`/`times_retired` foram repontadas pra rank/promoções (mantendo os
nomes por compatibilidade com o schema do banco).

### 4.2 Missões concluídas vs. partidas jogadas (⚠️ NÃO é `NumberOfGamesPlayed`)

Outra armadilha, achada em 02/08/2026: a tela de estatísticas do jogo mostra
**"Missions Completed"** (no teste: 445), mas esse número **NÃO** é o escalar
`NumberOfGamesPlayed`. Esse escalar conta **toda partida iniciada** — incluindo as
abandonadas/falhadas — e valeu **504** no mesmo save. Ler `NumberOfGamesPlayed` e
rotular de "missões" dá 59 a mais.

O "concluídas" mora dentro de um bloco **`MissionStatsSave`** (logo no começo do
save), que é um array chamado `Counters`. **Cada entrada tem 3 campos, em ordem:**
`PlayerClassID` (Guid 16 bytes) → `MissionStatID` (Guid 16 bytes) → `Value`
(`FloatProperty`, 4 bytes). Ou seja, **cada estatística é guardada POR CLASSE**; o
total que o jogo exibe é a **SOMA das 4 classes** de um mesmo `MissionStatID`.

- GUID confirmado de "missões concluídas": **`8ae243468b5da06e7bd0e4c806000000`**
  (soma = 445, batendo com o print). Por classe: Gunner 127 + Driller 70 +
  Engineer 114 + Scout 134 = 445. ✔ (Os GUIDs de classe aqui batem com `CLASS_GUIDS`.)
- Existem **~93 stats distintas** nesse bloco (334 entradas / ~4 por stat). Só
  mapeamos a de missões concluídas por enquanto; o mesmo método (somar por
  `MissionStatID` e casar com um número conhecido) serve pra mapear as outras.
- Candidatos a "Solo Missions Completed" (28 no print): há 2 stats somando 28
  (`9d293c4a…` e `000efb43…`) — ambíguo sem confirmação, não mapeado ainda.

Isso vive em `parse_mission_stat(data, stat_guid)` + a constante
`MISSIONS_COMPLETED_STAT` no parser. O `parse_save` devolve `missions_completed`.
No banco virou a coluna `missions_completed` (ver seção 6); no dashboard virou a
métrica "Missões concluídas", ao lado de "Partidas jogadas" (o antigo 504).

### 4.3 Overclocks e cosméticos (o que você TEM vs o TOTAL)

O save guarda **o que você possui**, não o catálogo do jogo. Duas listas importam:

- **`ForgedSchematics`** — `ArrayProperty` de `StructProperty(Guid)`. São os schematics
  que você **forjou**: overclocks de arma **+** cosméticos vindos de matrix core, tudo
  misturado. No teste: **151 GUIDs**.
- **`UnLockedVanityItemIDs`** — mesmo formato. Cosméticos desbloqueados (**154**).

Pra virar "tenho X de Y", precisa do **catálogo** (o Y), que **não está no save** — vem do
`guids.json` (a "tabela de referência", igual o `all_drg_enemies.json` foi pros bichos). Ele
tem: `Weapons` (**160 overclocks**, com arma/classe/nome/custo), e cosméticos (`Headwear`
36, `Moustache` 44, `Beard` 144, `Sideburns` 28, `Victory Moves` 36, `Weapon Skins` 60).

- **Encoding do GUID:** casa **direto no hex MAIÚSCULO** (nada de byte-swap). Confirmado:
  100 dos 151 forjados batem com os 160 overclocks → **overclocks: 100/160**. Os outros
  51 forjados são cosméticos de matrix core.
- **⚠️ Cosméticos são incertos:** a contagem sai baixa (ex.: Headwear 1/36) porque o
  desbloqueio de vanity tem várias fontes (rank, pass, matrix core…) e `UnLockedVanityItemIDs`
  sozinho não cobre tudo. No dashboard a seção de cosméticos é marcada como **estimativa**.
- Overclocks é sólido. Vive em `parse_guid_array(data, name)` no parser; o `parse_save`
  devolve `forged_schematics` e `vanity_items`. O **dashboard lê o save ATUAL** (não o
  banco) e cruza com o `guids.json` na aba "⚙️ Overclocks".

---

## 5. Os arquivos, um por um

### `drg_save_parser.py` — o tradutor do save
**Função:** ler o arquivo `.sav` cru e devolver os dados em forma organizada. Não depende de nada externo (só a biblioteca padrão do Python).

Peças principais (funções):
- `read_fstring(data, pos)` — lê um texto no formato FString a partir de uma posição.
- `find_property(data, name)` — acha onde uma propriedade começa, casando a codificação **exata** do nome (evita falso positivo de substring).
- `read_scalar(data, name)` — lê um número único (Credits, PerkPoints, etc.).
- `parse_guid_map(data, name)` — lê um mapa GUID→valor (serve pra `EnemiesKilled` **e** `OwnedResources`).
- `parse_classes(data)` — lê os 4 blocos de classe e devolve level/promoções por classe (ver seção 4.1).
- `level_from_xp(xp)` — converte o XP de uma classe no level 1–25 (tabela `CLASS_XP_TABLE`).
- `parse_mission_stat(data, stat_guid)` — soma o `Value` de um `MissionStatID` entre as classes (ver seção 4.2). Usado pra `missions_completed`.
- `parse_guid_array(data, name)` — lê um `ArrayProperty` de `StructProperty(Guid)` e devolve a lista de GUIDs em hex MAIÚSCULO. Usado pra `ForgedSchematics` e `UnLockedVanityItemIDs` (ver seção 4.3).
- `parse_save(path, enemy_names=None)` — junta tudo e devolve um **dicionário** com: `player_rank`, `promotions`, `classes`, `level` (=rank), `credits`, `perk_points`, `games_played` (=partidas jogadas, 504), `missions_completed` (=missões concluídas, 445), `times_retired` (=promoções), `playtime_seconds`, `total_kills`, `species_count`, `kills_by_guid`, `kills_named`, `resources_by_guid`, `forged_schematics` (overclocks+cosm. forjados), `vanity_items` (cosméticos).
- `KNOWN_ENEMIES` — mapa mínimo de GUID→nome embutido (só o Grunt confirmado; o resto vem do `all_drg_enemies.json`).

Como rodar sozinho (mostra um resumo no terminal):
```bash
python drg_save_parser.py "caminho/do/save.sav" all_drg_enemies.json
```

### `all_drg_enemies.json` — a tabela de tradução dos bichos
Um dicionário `{ "guid": "Nome do bicho" }` com as 77 espécies. Foi montado cruzando as
**contagens** de kills: as screenshots do bestiário deram (nome → contagem), o save deu
(GUID → contagem), e a contagem serviu de "cola" pra ligar os dois (um **JOIN** pela contagem).

⚠️ **Incertezas conhecidas** (ver seção 7):
- 3 nomes foram deduzidos por eliminação (o OCR não leu o número): **Naedocyte Cave Cruiser (2487)**, **Maggot (331)**, **Silicate Harvester (39)**. Confirmar olhando o bestiário no jogo.
- 4 pares têm contagem **idêntica**, então o pareamento GUID↔nome dentro do par é um chute (cosmético, já que o número é o mesmo): 247 (Ebonite Praetorian / Cave Leech), 38 (Hiveguard / Huuli Hoarder), 16 (Deeptora Honeycomb / Ossiran Bone Collector), 11 (Korlok Tyrant-Weed / Rival Tech Nemesis).

### `guids.json` — a tabela de referência de overclocks/cosméticos
Um dicionário grande `{ categoria: { "GUID": {meta} } }` (ver seção 4.3). Categorias:
`Weapons` (160 overclocks, com `dwarf`/`weapon`/`name`/`cost`), e cosméticos (`Cosmetic -
Headwear/Moustache/Beard/Sideburns`, `Victory Moves`, `Weapon Skins`). É o "Y" do
comparativo — o save só diz o que você TEM; este arquivo diz o TOTAL. GUID casa em hex
MAIÚSCULO com o `ForgedSchematics` do save.

### `snapshot.py` — tira a "foto" e guarda no banco
**Função:** rodar o parser, pegar os números e gravar UMA foto POR DIA no banco SQLite
(ver seção 6). Feito pra funcionar num PC zerado.

O que ele faz de esperto:
- **Acha o save sozinho** (`find_save`) em QUALQUER drive: além dos caminhos padrão, lê o registro da Steam + o `libraryfolders.vdf` (`_steam_libraries`) pra achar bibliotecas em `D:`, `E:`, etc. Também aceita caminho por argumento / variável `DRG_SAVE`. (Não cobre a versão Game Pass/Microsoft Store — aí usar `DRG_SAVE`.)
- **Cria o banco na 1ª vez** (`conectar` roda o `SCHEMA_SQL` com `CREATE TABLE IF NOT EXISTS`).
- **Não duplica** (`tirar_snapshot`): se a última foto tem os mesmos kills e tempo, não grava de novo (dedup).
- **UMA foto por DIA** (`tirar_snapshot` + `_data_local`): se a última foto é de HOJE (data local), ATUALIZA ela pro estado mais recente em vez de criar outra. Banco leve (1 linha/dia) e delta dia-a-dia limpo. Ver seção 6.
- **Mostra o que cresceu** (`mostrar_deltas`) desde a foto anterior, comparando as duas últimas.

Como rodar:
```bash
python snapshot.py                 # acha o save e tira uma foto
python snapshot.py "caminho.sav"   # aponta o save manualmente
python snapshot.py --loop 30       # tira uma foto a cada 30 minutos
```
Precisa do `drg_save_parser.py` e (opcional) do `all_drg_enemies.json` na mesma pasta.

### `watcher.py` — o "vigia" do save (captura automática) **(FEITO ✅)**
**Função:** rodar em segundo plano e tirar foto SOZINHO — pra ninguém precisar rodar
o `snapshot.py` na mão. Reaproveita as funções do `snapshot.py` (`find_save`,
`load_names`, `conectar`, `tirar_snapshot`). Só stdlib.

Dispara nos 3 momentos-chave:
1. **jogo abre** → foto de abertura (baseline da sessão);
2. **save reescrito** → o DRG regrava o `.sav` ao fim da missão (voltar pro Space Rig);
   o vigia vê a data de modificação mudar e tira foto (o **dedup** evita gravar repetido,
   então o banco não incha);
3. **jogo fecha** → foto final e o vigia encerra sozinho.

Detecção do jogo: pergunta ao SO se o processo `FSD-Win64-Shipping.exe` está vivo
(`tasklist` no Windows, `pgrep` no Linux). Se não der pra detectar, cai no "modo
arquivo" (roda até Ctrl+C ou `--minutos`).

**Como deixar 100% automático (a sacada da praticidade):** via **Launch Options da
Steam**, usando o lançador `drg_watcher_launch.bat`. Jeito fácil: rodar
`configurar_steam.bat` (duplo clique) — ele monta a linha com o caminho DESTE PC e
copia pro clipboard; aí é só colar em Propriedades → Geral → Opções de Inicialização.
A linha tem a cara:
```
"C:\...\Papaio-Stats\drg_watcher_launch.bat" %command%
```
O `%command%` é o próprio DRG (a Steam troca por ele). O `.bat` sobe o vigia escondido
e depois entrega o jogo. Assim o vigia liga junto com o DRG e o jogador só clica Jogar.

⚠️ **NÃO funcionou** a linha "esperta" `cmd /c start "" /min pythonw "...watcher.py" &
%command%` direto nas Launch Options (a Steam abriu um cmd e não rodou nada; o
`watcher.log` nem foi criado). O `.bat`-wrapper é o jeito confiável — testado.

Uso manual / teste:
```bash
python watcher.py                 # acha o save, espera o jogo, vigia
python watcher.py --sem-processo --minutos 60   # modo arquivo, para em 60 min
python watcher.py --intervalo 5   # checa a cada 5s (padrão: 8)
```
Log de tudo em `watcher.log` (UTF-8). **Por que NÃO é um mod do mod.io:** mods de DRG
são Blueprint numa sandbox fechada — não leem arquivo, não rodam Python, não abrem
navegador. Só código NATIVO (tipo o loader `mint`, em Rust, que injeta DLL) escapa
disso, e isso é pesado/frágil demais pra este projeto. Por isso a captura é externa
(este vigia), não um mod. (Ver seção 7.)

### `drg_watcher_launch.bat` — o lançador pra Steam **(FEITO ✅)**
Um `.bat` de 2 linhas úteis que vai nas **Launch Options da Steam** (ver `watcher.py`
acima). Faz: `start "" /min pythonw "%~dp0watcher.py"` (sobe o vigia escondido, do lado
do próprio `.bat`) e depois `%*` (lança o jogo e segura enquanto ele roda, como a Steam
espera). É o jeito **confiável** de ligar o vigia junto do jogo — o `& %command%` solto
nas Launch Options não funcionou. Testado.

### `configurar_steam.bat` — gera a linha da Steam e copia pro clipboard **(FEITO ✅)**
Resolve a chatice de digitar o diretório inteiro nas Launch Options. Usa `%~dp0` pra
descobrir a própria pasta, monta `"<pasta>\drg_watcher_launch.bat" %command%` e joga no
clipboard (via arquivo temp + `clip`, que evita espaço/quebra do `echo | clip`). Duplo
clique → cola na Steam com Ctrl+V. Funciona em qualquer PC sem editar nada.
> Detalhe de batch: pra imprimir um `%command%` LITERAL (sem a Steam expandir), no `.bat`
> escreve-se `%%command%%` — o `%%` vira um `%` só na saída.

### `dashboard.py` — o painel com gráficos **(FEITO ✅)**
Lê o `drg_stats.db` e desenha um site interativo: ranking de kills por espécie, evolução
das métricas ao longo do tempo, créditos, tempo de jogo, e o "quanto matou desde a última
foto". Feito com **Streamlit** (biblioteca que transforma script Python em site) + **Altair**
(gráficos) + **pandas** (tabelas de dados). Os dois últimos já vêm junto com o Streamlit, então
a única dependência a instalar é o Streamlit.

Tem um botão **"📸 Atualizar agora"** que lê o save e grava uma foto nova sem terminal —
reaproveita as funções do `snapshot.py`. Detalhe importante pra estudo: **toda a explicação
linha-a-linha desse arquivo (funções, lógica, sintaxe do Streamlit e do Altair, como
editar/reutilizar) está na [Seção 11](#11-aula-completa-o-dashboardpy-e-o-streamlit).**

Como rodar (jeito manual):
```bash
pip install streamlit
streamlit run dashboard.py
```

### `abrir_dashboard.bat` — o atalho de duplo clique (Windows)
Um arquivo `.bat` (script do prompt do Windows). **Duplo clique nele abre o painel** sem
precisar de terminal: ele acha o Python, instala o Streamlit na 1ª vez se faltar, e roda o
`streamlit run dashboard.py`. É o que torna o projeto usável por quem não é dev. Explicado
linha-a-linha na Seção 11.7.

### `.streamlit/config.toml` — o tema fixo do painel
Arquivo de configuração que o Streamlit **lê sozinho** ao rodar (a pasta `.streamlit` na raiz
do projeto é uma convenção do próprio Streamlit). Guarda as cores do tema (fundo preto,
laranja DRG). Explicado na Seção 11.6.

### `renomeador.py` — utilitário avulso (NÃO faz parte do pipeline do DRG)
Vigia uma pasta e renomeia imagens novas pra 1, 2, 3... É uma ferramenta separada, sem
relação com o pipeline do tracker de DRG. Ignorar quando estiver trabalhando no tracker.

---

## 6. O banco de dados (schema explicado)

São **duas tabelas** numa relação **um-para-muitos**: uma foto (`snapshots`) tem várias
linhas de contagem (`kills`).

```sql
snapshots ( id, taken_at, save_file, level, credits, perk_points,
            games_played, missions_completed, times_retired,
            playtime_seconds, total_kills )

kills ( snapshot_id, guid, name, count )      -- ligada a snapshots por snapshot_id
```

> **Migração de coluna:** `missions_completed` foi adicionada DEPOIS que o banco já
> existia. Como `CREATE TABLE IF NOT EXISTS` não altera tabela existente, o
> `snapshot.py` tem `_migrar()` (roda `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`
> só do que falta — idempotente). Fotos antigas ficam com `missions_completed = NULL`
> (não dá pra saber o valor histórico; **não se fabrica histórico**). Só a foto que
> corresponde ao save atual foi backfillada com 445.

> **UMA foto por DIA (regra de gravação).** O `tirar_snapshot` não cria uma linha a cada
> missão (encheria: 30 missões = 30 linhas). Se já existe foto de HOJE (data **local**, via
> `_data_local`), ele **atualiza** essa linha (UPDATE + troca os kills dela) pro estado mais
> recente; senão, cria uma nova. Resultado: cada dia = estado do **fim** do dia, banco leve,
> e delta dia-a-dia = "o que fiz naquele dia". O dedup (não gravar se nada mudou) continua
> valendo por cima.

Ideias por trás disso (importantes):
- **Guardamos fatos, não derivados.** As contagens ficam salvas; o "quanto cresceu" e o ranking são **calculados na hora** com SQL. Guardar o delta deixaria ele desatualizado. (Regra: *estado derivado se calcula, não se armazena.*)
- **Guardamos o GUID sempre + o nome como opcional (pode ser NULL).** O GUID é a chave estável que sempre existe; o nome é só enriquecimento e pode ser preenchido depois. Assim até bicho sem nome mapeado é rastreado.
- **Chave primária composta** em `kills` = `(snapshot_id, guid)`: garante que não exista a mesma espécie duas vezes na mesma foto.

---

## 7. Armadilhas e lembretes (gotchas)

- **SQLite ignora FOREIGN KEY por padrão.** Tem que rodar `PRAGMA foreign_keys = ON;` em **toda** conexão, senão o `ON DELETE CASCADE` não acontece e nem dá erro — só silenciosamente não funciona.
- **Nunca monte SQL com f-string.** Use sempre `?` (consulta parametrizada). Protege contra SQL injection e trata aspas/vírgulas/nulos corretamente.
- **OCR é não-confiável.** Ao ler número de tela, sempre **valide contra um conjunto de valores que você sabe que existem** (aqui: as contagens do próprio save). Leitura que não bate com nenhum valor válido = descartar e tentar de novo.
- **Busca por substring em binário é perigosa.** Casar `"Level"` pega dentro de `"RetiredCharacterLevels"`. Sempre casar a codificação exata (tamanho + texto + `\0`).
- **Contagem duplicada = ambiguidade irresolvível** só com os dados. É por isso que chave única (PRIMARY KEY) importa. (Os 4 pares da seção 5.)
- **`renomeador.py` é destrutivo** (renomear não tem "desfazer"). Testar em cópias antes de apontar pra fotos importantes.
- **`pythonw` não tem console: `sys.stdout` pode ser `None`.** Um `print()` num processo lançado com `pythonw` (como o vigia via Steam) pode estourar `AttributeError`. Por isso o `watcher.py` loga num ARQUIVO (UTF-8) e só tenta o console guardado por `if sys.stdout is not None`.
- **Console do Windows é cp1252: emoji quebra o `print`.** Imprimir `📸`/`—` no console padrão dispara `UnicodeEncodeError`. O log-arquivo é UTF-8 (aguenta tudo); o print no console vai dentro de `try/except`.
- **Diretório de trabalho não é garantido.** Quando a Steam lança o vigia, o CWD pode ser a pasta do JOGO. O `watcher.py` faz `os.chdir(pasta_do_script)` no começo pra `drg_stats.db`, `all_drg_enemies.json` e `watcher.log` caírem no lugar certo.
- **"Hoje" é a data LOCAL, não a UTC.** A regra de uma-foto-por-dia agrupa por dia do fuso do PC (`_data_local` converte o `taken_at` UTC pro local antes de pegar `.date()`). Se agrupasse por dia UTC, uma sessão às 22h no Brasil (01h UTC do dia seguinte) cairia no dia errado.
- **Overclocks vêm do SAVE, não do banco.** O comparativo é estado ATUAL, então o dashboard lê o save na hora (cacheado com `@st.cache_data`) e cruza com o `guids.json`. Consequência: num PC SEM o save (só o banco), a aba de overclocks não tem o que mostrar — por isso ela tem guarda de "não achei o save".
- **Guardar em UTC, EXIBIR em local.** O `taken_at` é gravado em UTC (certo — é neutro de fuso). Mas exibir exige converter pro fuso do PC, senão o painel mostra a hora de Londres (deu 22:06 em vez de 19:06 no Brasil). O erro clássico é `pd.to_datetime(x, utc=True).dt.tz_convert(None)` — isso tira o fuso MANTENDO o relógio UTC. Certo: `.dt.tz_convert(fuso_local).dt.tz_localize(None)`, com `fuso_local = datetime.now().astimezone().tzinfo` (pega o fuso do PC sozinho, sem hardcode).
- **`subprocess` sob `pythonw` PISCA janelinha e rouba o foco.** Rodando via `pythonw` (sem console), cada `subprocess.run(["tasklist", ...])` abre uma janela de console que aparece por um instante e **rouba o foco** da janela ativa — insuportável se o vigia checa a cada poucos segundos. Correção: passar `creationflags=CREATE_NO_WINDOW` (0x08000000) no `subprocess` (só Windows). É a constante `_SEM_JANELA` no `watcher.py`.
- **Mod de DRG NÃO alcança o nosso pipeline.** Mods do mod.io são Blueprint numa sandbox fechada (sem I/O de arquivo, sem processo, sem rede). Só código nativo (ex.: o loader `mint`, em Rust, que injeta DLL e faz hook na engine) fura isso — pesado e frágil demais aqui. Por isso a captura automática é o `watcher.py` (externo), não um mod.

---

## 8. Status do projeto

**Feito:**
- [x] Confirmado que o save contém kills por espécie (engenharia reversa do formato GVAS).
- [x] `drg_save_parser.py` — extrai kills, recursos e escalares. Testado.
- [x] `all_drg_enemies.json` — 77 GUIDs traduzidos (com as ressalvas da seção 5/7).
- [x] `snapshot.py` — grava fotos no SQLite, acha o save sozinho, não duplica, mostra deltas. Testado.
- [x] **`dashboard.py`** (Streamlit) — métricas com variação, ranking por espécie, evolução temporal, deltas, tabela com busca e export CSV. Botão "Atualizar agora". Tema DRG. Testado (sobe sem erro, lê os dados reais).
- [x] `abrir_dashboard.bat` + `.streamlit/config.toml` — duplo clique abre o painel; tema fixo.
- [x] **`missions_completed`** (missões concluídas, 445) — descoberto no bloco `MissionStatsSave` (seção 4.2). Separado de `games_played` (partidas jogadas, 504). Parser + coluna no banco (com migração) + métrica no dashboard. Testado.
- [x] **`watcher.py`** — vigia o save e tira foto sozinho (abertura / fim de missão / fechamento). Loga em arquivo UTF-8, ancora o CWD, detecta o processo do jogo sem piscar janela (`CREATE_NO_WINDOW`). Testado (os 3 gatilhos + dedup). Ver seção 5/7.
- [x] **`drg_watcher_launch.bat` + `configurar_steam.bat`** — lançador pra Steam (sobe vigia + jogo) e gerador da linha de Launch Options (copia pro clipboard). Testado.
- [x] **Fuso horário no dashboard** — agora exibe no fuso LOCAL do PC (era UTC). Ver gotcha na seção 7.
- [x] **Comparativo de overclocks** (aba "⚙️ Overclocks"): 100/160 por arma, barra de progresso, lista do que falta forjar. Lê o save atual + cruza com `guids.json`. Cosméticos como estimativa. Ver seção 4.3. Testado.
- [x] **Uma foto por dia** (`tirar_snapshot` atualiza a foto de hoje em vez de somar). Banco leve, delta dia-a-dia limpo. Ver seção 6. Testado.
- [x] **Plug-and-play em qualquer PC** — `find_save` acha o DRG em qualquer drive (registro Steam + `libraryfolders.vdf`, via `_steam_libraries`). Caminhos todos auto-localizados (`%~dp0`, `os.chdir`, fuso automático). Único pré-req: Python instalado. Testado (encontra bibliotecas em outros drives).
- [x] **GitHub-ready** — `README.md` (visão geral + instalação + créditos), `logica.md` (a engenharia reversa explicada do zero, byte por byte) e `.gitignore` (ignora `drg_stats.db`, `watcher.log`, `*.sav`, `__pycache__`, `mint-master/`, screenshots pessoais).
- [x] **Bilíngue (EN/PT)** — `README.md` e `logica.md` têm inglês primeiro, português depois. **Comentários e docstrings do código traduzidos pra inglês** (parser, snapshot, watcher, dashboard, `.bat`s). Os textos de TELA (UI do dashboard, prints, log do watcher, echos dos `.bat`) seguem em PT de propósito. A documentação técnica interna segue em PT. O `.bat` do painel se chama `abrir_dashboard.bat` (minúsculo).

**A fazer:**
- [ ] Cosméticos: contagem confiável (mapear as outras fontes de vanity além de `UnLockedVanityItemIDs`).
- [ ] Cravar a linha exata das Launch Options da Steam (testar aspas/`%command%`) e um passo-a-passo no README.
- [ ] Confirmar no bestiário os 3 nomes deduzidos (Naedocyte Cave Cruiser / Maggot / Silicate Harvester).
- [ ] (Opcional) Mapear "Solo Missions Completed" (28) e outras stats do `MissionStatsSave` (seção 4.2).
- [ ] (Opcional) Tabela `resources` no banco, mesmo padrão do `kills`.
- [ ] (Opcional) Agendar o `snapshot.py` (Task Scheduler no Windows / cron ou systemd no Arch).
- [ ] (Futuro) Mapear GUID→nome pelos arquivos `.pak` do jogo pra resolver os pares ambíguos de vez.
- [ ] README caprichado contando a história (engenharia reversa → ETL → dashboard).

---

## 9. Como rodar o projeto do zero

```bash
# 1. Ter Python 3.10+ instalado.
# 2. Colocar drg_save_parser.py, all_drg_enemies.json e snapshot.py na mesma pasta.

# 3. Tirar a primeira foto (cria o banco drg_stats.db):
python snapshot.py

# 4. (Opcional) Captura automática enquanto joga:
#    - rode configurar_steam.bat (duplo clique) -> copia a linha pro clipboard
#    - cole em Steam -> DRG -> Propriedades -> Opções de Inicialização
#    (ou, na mão: python watcher.py)

# 5. Abrir o painel — jeito FÁCIL (Windows): duplo clique em "abrir_dashboard.bat".
#    Jeito manual (qualquer SO):
pip install streamlit
streamlit run dashboard.py
```
Só o `dashboard.py` precisa de biblioteca externa (Streamlit; o pandas e o altair vêm junto
com ele). Parser, snapshot e watcher rodam com Python puro.

---

## 10. Glossário rápido

- **GVAS**: formato de arquivo de save da engine Unreal.
- **GUID**: identificador único de 16 bytes (aqui, o "código" de cada inimigo).
- **little-endian**: ordem de bytes com o menos significativo primeiro.
- **parser**: programa que lê e interpreta um formato de dado.
- **ETL**: Extract-Transform-Load (extrair, transformar, carregar) — o arco de um pipeline de dados.
- **snapshot**: uma "foto" dos dados num instante; juntando várias, forma histórico.
- **schema**: o desenho das tabelas do banco (nomes, colunas, tipos, chaves).
- **JOIN**: juntar duas tabelas por uma coluna em comum.
- **PK / FK**: Primary Key (chave única que identifica a linha) / Foreign Key (coluna que aponta pra outra tabela).
- **idempotente**: rodar 1 vez ou 100 vezes dá o mesmo resultado (ex.: `CREATE TABLE IF NOT EXISTS`).
- **consulta parametrizada**: SQL com `?` no lugar dos valores, preenchidos com segurança pelo driver.
- **Streamlit**: biblioteca que transforma um script Python num site interativo, sem HTML/JS.
- **Altair**: biblioteca de gráficos baseada na "gramática dos gráficos" (você descreve o dado, ela desenha).
- **DataFrame**: a "planilha na memória" do pandas — linhas e colunas, com nome em cada coluna.
- **widget**: um controle interativo na tela (botão, slider, caixa de seleção…).

---

## 11. Guia completo: o `dashboard.py` e o Streamlit

Esta seção é o guia detalhado do painel. Leia na ordem; cada parte assume a anterior.
No fim dá pra **ler, editar e reusar** qualquer pedaço do `dashboard.py`.

### 11.0 A ideia mais importante do Streamlit (leia isto ANTES de tudo)

O Streamlit tem **um** conceito central, e se você entender ele, o resto é fácil:

> **Toda vez que você mexe em qualquer coisa na tela, o Streamlit RE-RODA o seu
> script inteiro, de cima até embaixo, do zero.**

Não existe "cadê o código que responde ao clique do botão?" como em outras linguagens.
Não tem isso. O jeito Streamlit é: o script roda inteiro, desenhando a tela na ordem em
que as funções `st.*` aparecem. Você clica num slider → o Streamlit roda o script TODO de
novo, e agora a variável do slider tem o valor novo → a tela sai diferente.

Consequências práticas (grave estas três):
1. **A ordem das linhas = a ordem das coisas na tela.** `st.title(...)` antes de
   `st.dataframe(...)` significa título em cima, tabela embaixo. Quer mudar o layout?
   Muda a ordem das linhas.
2. **Variáveis normais não "lembram" entre re-execuções.** Cada re-run começa do zero.
   Pra lembrar de algo entre um clique e outro, existe o `st.session_state` (um dicionário
   que sobrevive) — usamos ele pra passar a mensagem do botão "Atualizar agora" (§11.4).
3. **Um `st.button(...)` devolve `True` só no exato re-run causado pelo clique** — no
   próximo re-run ele já volta a `False`. Por isso o padrão é sempre
   `if st.button(...):` com a ação logo dentro do `if`.

Isso explica por que o `dashboard.py` é escrito "de cima pra baixo, sem função main":
o próprio arquivo, lido na ordem, **é** a página.

### 11.1 O mapa do arquivo (o que vem em qual ordem)

```
1. imports                     -> traz streamlit, altair, pandas e o nosso snapshot.py
2. constantes de COR           -> a paleta do tema (§11.5)
3. funções de ACESSO AO BANCO  -> conectar / carregar_snapshots / carregar_kills / carregar_deltas
4. funções FORMATADORAS        -> fmt_num / fmt_horas / fmt_quando (número bonito)
5. função atualizar_agora()    -> o que o botão 📸 chama (usa o snapshot.py)
6. funções de GRÁFICO (Altair) -> grafico_barras_especies / grafico_evolucao
7. "APLICAÇÃO" (o corpo)        -> daqui pra baixo é a página em si, na ordem da tela:
     set_page_config -> CSS -> título -> guarda de banco-vazio ->
     sidebar -> métricas -> abas (espécie / evolução / desde / tabela)
```

Repare no padrão: **primeiro definimos ferramentas (funções), depois usamos elas** no
corpo. Isso mantém o corpo curto e legível — dá pra ler o corpo como um roteiro.

### 11.2 As funções de acesso ao banco (pandas + SQLite)

```python
def conectar() -> sqlite3.Connection | None:
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```
- **`Path(DB_PATH).exists()`**: checa se o arquivo do banco existe. Se não, devolvemos
  `None` — o corpo trata isso mostrando a tela "tire a primeira foto".
- **`sqlite3.connect(...)`**: abre o banco. O painel só LÊ (quem escreve é o `snapshot.py`).
- **`row_factory = sqlite3.Row`**: faz cada linha vir acessível por nome de coluna. Não é
  estritamente necessário aqui (o pandas cuida disso), mas é boa prática.

```python
def carregar_snapshots(conn) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM snapshots ORDER BY id ASC", conn)
    if not df.empty:
        fuso_local = datetime.now().astimezone().tzinfo
        df["quando"] = (pd.to_datetime(df["taken_at"], utc=True)
                        .dt.tz_convert(fuso_local).dt.tz_localize(None))
    return df
```
- **`pd.read_sql_query(sql, conn)`**: roda o SQL e devolve o resultado já como um
  **DataFrame** (a "planilha na memória"). É a ponte SQLite → pandas.
- **`df["quando"] = ...`**: cria uma coluna NOVA no DataFrame. `taken_at` está guardado
  como texto ISO **em UTC** (ex.: `"2026-08-01T01:31:23+00:00"`). `pd.to_datetime(..., utc=True)`
  transforma em data/hora de verdade; `.dt.tz_convert(fuso_local)` traz pro fuso do PC
  (senão o painel mostraria a hora de Londres); `.dt.tz_localize(None)` tira o timezone
  (deixa "ingênua") pro Altair/strftime. `fuso_local` vem de `datetime.now().astimezone().tzinfo`.
  (Ver o gotcha "Guardar em UTC, EXIBIR em local" na seção 7.)

```python
def carregar_kills(conn, snapshot_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT guid, name, count FROM kills WHERE snapshot_id = ? ORDER BY count DESC",
        conn, params=(snapshot_id,))
    df["especie"] = df["name"].fillna("GUID:" + df["guid"].str.slice(0, 8))
    return df
```
- **`params=(snapshot_id,)`** com o `?` no SQL = **consulta parametrizada** (a regra de
  ouro da seção 7: nunca montar SQL com f-string). A vírgula em `(snapshot_id,)` é
  obrigatória — é o que faz o Python entender que é uma tupla de 1 elemento.
- **`df["name"].fillna(...)`**: `name` pode ser NULL (bicho sem tradução). `fillna`
  preenche esses vazios. `df["guid"].str.slice(0, 8)` pega os 8 primeiros caracteres do
  GUID. Resultado: se tem nome, mostra o nome; se não, mostra `GUID:e977bf0a`. Assim a
  tela nunca fica com célula vazia.

```python
def carregar_deltas(conn, id_atual, id_anterior) -> pd.DataFrame:
    # ...SELECT com LEFT JOIN entre a foto de agora (k2) e a anterior (k1)...
    # delta = k2.count - COALESCE(k1.count, 0)
```
- Este é o **mesmo JOIN** que o `snapshot.py` usa no `mostrar_deltas`, só que devolvendo
  DataFrame pro painel. `COALESCE(k1.count, 0)` = "se não existia esse bicho na foto
  antiga, conta como 0" (ex.: uma espécie nova). Repare que usei `params={"ant":..., "atu":...}`
  — dá pra parametrizar por **nome** (`:ant`) em vez de posição (`?`); os dois jeitos valem.

### 11.3 Os formatadores (número gigante → legível no padrão BR)

```python
def fmt_num(n) -> str:
    if n is None: return "—"
    return f"{int(n):,}".replace(",", ".")
```
- **`f"{int(n):,}"`**: o `:,` dentro de uma f-string é um "mini-formato" do Python que
  põe separador de milhar. `75466` vira `"75,466"`. Como o padrão do Python é vírgula (EUA)
  e a gente quer ponto (BR), troco com `.replace(",", ".")` → `"75.466"`.
- `fmt_horas` faz o mesmo com uma dança de `replace` pra virar `"34,3 h"` (vírgula decimal).
  O truque do `"X"` no meio é só pra não trocar ponto e vírgula um por cima do outro.
- **Como reusar:** qualquer número que você jogar na tela, passe por `fmt_num(...)` pra
  ficar no padrão brasileiro.

### 11.4 `atualizar_agora()` — o botão que grava foto sem terminal

```python
def atualizar_agora() -> str:
    save_path = snapshot.find_save()
    if save_path is None or not save_path.exists():
        return "❌ Não achei o save..."
    names = snapshot.load_names()
    conn = snapshot.conectar(DB_PATH)
    try:
        snap_id = snapshot.tirar_snapshot(conn, save_path, names)
    finally:
        conn.close()
    if snap_id is None:
        return "ℹ️ Nada mudou..."
    return f"✅ Foto nova gravada (snapshot #{snap_id})! ..."
```
- **A grande sacada:** em vez de reescrever a lógica de gravar, a gente **importou o
  `snapshot.py`** (`import snapshot` lá no topo) e chamou as funções dele:
  `find_save`, `load_names`, `conectar`, `tirar_snapshot`. Reuso puro — o painel só
  "aperta os botões" do módulo que já existe e foi testado.
- **`try/finally`** garante que o banco seja fechado (`conn.close()`) mesmo se der erro no
  meio. É a forma segura de mexer em arquivo/conexão.
- A função devolve uma **string de mensagem** (não desenha nada). Quem desenha é o corpo,
  com `st.info(msg)`. Separar "fazer" de "mostrar" deixa a função testável.

Como isso vira interação (no corpo, dentro da sidebar):
```python
if st.button("📸 Atualizar agora", type="primary", width='stretch', help="..."):
    with st.spinner("Lendo o save..."):
        msg = atualizar_agora()
    st.session_state["_msg_atualizar"] = msg
    st.rerun()
if "_msg_atualizar" in st.session_state:
    st.info(st.session_state.pop("_msg_atualizar"))
```
- **`st.button(...)`** devolve `True` no re-run do clique → entra no `if`.
- **`with st.spinner("..."):`** mostra uma rodinha "carregando" enquanto o bloco roda.
- Aqui aparece o **`st.session_state`** (§11.0, ponto 2): eu guardo a mensagem nele e
  chamo **`st.rerun()`** (re-roda o script na hora, pra a tela já refletir a foto nova).
  Como o `st.rerun()` recomeça tudo, se eu mostrasse a mensagem antes dela sumiria; então
  guardo no `session_state`, e no re-run seguinte eu leio e removo com `.pop(...)` (mostra
  uma vez e limpa). É o padrão "mensagem que sobrevive a um rerun".

### 11.5 Os gráficos com Altair (a "gramática dos gráficos")

Altair funciona diferente do que a gente imagina de "fazer gráfico". Você **não** diz
"desenhe uma barra no pixel X". Você **descreve o dado**: "o eixo Y é a espécie, o eixo X é
a contagem, a cor representa a magnitude" — e o Altair desenha. Isso se chama *gramática
dos gráficos*. As três peças são sempre:

1. **`alt.Chart(dados)`** — de qual DataFrame vem o dado.
2. **`.mark_*()`** — o formato do desenho: `mark_bar` (barra), `mark_line` (linha),
   `mark_text` (texto), `mark_point`…
3. **`.encode(...)`** — o **mapeamento**: qual coluna vai pra qual "canal" (x, y, cor,
   tooltip…).

O gráfico de barras:
```python
def grafico_barras_especies(df, top_n):
    d = df.head(top_n).copy()
    base = alt.Chart(d).encode(
        y=alt.Y("especie:N", sort="-x", title=None, axis=alt.Axis(...)),
        x=alt.X("count:Q", title="Kills", axis=alt.Axis(..., format="~s")),
    )
    barras = base.mark_bar(cornerRadiusEnd=4, height=alt.RelativeBandSize(0.72)).encode(
        color=alt.Color("count:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None),
        tooltip=[alt.Tooltip("especie:N", title="Espécie"),
                 alt.Tooltip("count:Q", title="Kills", format=",")],
    )
    rotulos = base.mark_text(align="left", dx=4, ...).encode(text=alt.Text("count:Q", format=","))
    altura = max(120, len(d) * 26)
    return (barras + rotulos).properties(height=altura).configure_view(strokeWidth=0)...
```
Decodificando cada pedaço:
- **`df.head(top_n)`**: pega só as `top_n` primeiras linhas (o DataFrame já veio ordenado
  por contagem). É o slider da sidebar controlando quantas barras aparecem.
- **`"especie:N"`** e **`"count:Q"`**: o sufixo diz o TIPO do dado pro Altair. `:N` =
  *Nominal* (categoria, texto: nomes de bicho). `:Q` = *Quantitativo* (número). `:T` =
  *Temporal* (data/hora, usado no gráfico de linha). Acertar o tipo é o que faz o eixo sair
  certo.
- **`sort="-x"`** no eixo Y: ordena as espécies pelo valor de X, decrescente. É o que faz a
  maior barra ficar no topo.
- **`format="~s"`** no eixo X: notação "curta" (10000 → `10k`). **`format=","`** no tooltip:
  separador de milhar (aqui deixei no estilo EUA pra simplicidade do tooltip).
- **`color=alt.Color("count:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None)`**: a cor
  representa a MAGNITUDE. `RAMP_LARANJA` é uma lista de laranjas do claro ao escuro — barra
  maior, laranja mais forte. **`legend=None`** tira a legenda de cor (a barra já se explica).
  *Aqui está a regra de dataviz que segui:* magnitude = **um tom só**, variando de claro a
  escuro (ramp sequencial), nunca uma cor diferente por barra (isso seria "arco-íris" e
  daria a falsa ideia de que a cor é uma categoria).
- **Camadas (layering):** `base.mark_bar(...)` desenha as barras e `base.mark_text(...)`
  desenha o número na ponta. O **`(barras + rotulos)`** com o operador `+` **empilha as duas
  camadas no mesmo gráfico**. Esse `+` é uma feature do Altair (sobrepor camadas).
- **`altura = max(120, len(d) * 26)`**: altura dinâmica — ~26px por barra, mínimo 120. Sem
  isso, com 77 espécies as barras ficariam achatadas.

O gráfico de linha (`grafico_evolucao`) segue a mesma receita, com `mark_line` e o eixo X
temporal (`"quando:T"`). Usei uma cor por métrica (laranja pra kills, amarelo pra créditos,
etc.) porque aqui cada gráfico é UMA linha só — cor é só identidade visual, não categoria.

**Como editar/reusar os gráficos:**
- Trocar a cor das barras: mexa na lista `RAMP_LARANJA` (§11.6).
- Barras na vertical em vez de horizontal: troque os papéis de X e Y (`x="especie:N"`,
  `y="count:Q"`).
- Novo gráfico de linha de outra métrica: chame `grafico_evolucao(snaps, "coluna_do_banco",
  "Título", "#cor")`. Funciona pra qualquer coluna numérica de `snapshots`.

### 11.6 O tema (cores) — em DOIS lugares

O visual escuro "caverna" vem de dois arquivos, e é bom saber por quê:

1. **`.streamlit/config.toml`** — o Streamlit lê esse arquivo **sozinho** ao iniciar (a
   pasta `.streamlit` na raiz do projeto é convenção dele). Define o tema base dos
   componentes padrão (fundo, cor primária dos botões/sliders, cor do texto):
   ```toml
   [theme]
   base = "dark"
   primaryColor = "#eb6834"
   backgroundColor = "#12100e"
   secondaryBackgroundColor = "#1c1917"
   textColor = "#f5efe6"
   ```
   Mexeu aqui, mudou a cara geral. **Precisa reiniciar** o `streamlit run` pra pegar.

2. **CSS injetado no `dashboard.py`** — pra coisas que o `config.toml` não alcança (deixar
   os cartões de métrica com borda arredondada, pintar o número da métrica de laranja).
   Isso é feito com:
   ```python
   st.markdown("<style> ... </style>", unsafe_allow_html=True)
   ```
   **`st.markdown`** normalmente escreve texto; com **`unsafe_allow_html=True`** ele aceita
   HTML/CSS cru. Os seletores tipo `[data-testid="stMetricValue"]` miram nas peças internas
   do Streamlit. Chama-se "unsafe" porque HTML cru pode ser perigoso se viesse de um usuário;
   aqui o texto é nosso, então é seguro.

As constantes `COR_*` e `RAMP_LARANJA` no topo do `dashboard.py` são a fonte única das cores
dos GRÁFICOS (Altair não lê o `config.toml`). Quer repintar tudo? Mexe nessas constantes +
no `config.toml`.

### 11.7 O corpo da página, de cima pra baixo (o roteiro)

- **`st.set_page_config(page_title=..., page_icon="🪨", layout="wide")`** — tem que ser a
  PRIMEIRA chamada `st.*` do script. `layout="wide"` usa a largura toda da tela.
- **Guarda de banco vazio:**
  ```python
  if conn is None or carregar_snapshots(conn).empty:
      st.warning(...); ...; st.stop()
  ```
  Se não há banco/fotos, mostra a tela "tire a primeira foto" e **`st.stop()`** encerra o
  script ali (não tenta desenhar gráficos sem dados). É o jeito Streamlit de fazer "return
  cedo".
- **A sidebar:** tudo dentro de `with st.sidebar:` aparece na barra lateral esquerda.
  - **`st.selectbox("Foto (snapshot)", lista)`** — caixa de seleção pra escolher qual foto
    olhar. Montei as opções com um *dict comprehension* (`{texto: id ...}`) e uso o texto
    escolhido pra achar o `id`. `snaps.iloc[::-1]` inverte a ordem (mais nova no topo);
    `.itertuples()` percorre as linhas do DataFrame uma a uma.
  - **`st.slider("Quantas espécies mostrar", 5, 77, 20)`** — controle deslizante: mínimo 5,
    máximo 77, valor inicial 20. O retorno vira a variável `top_n` usada nos gráficos.
- **As métricas (o cabeçalho de números):**
  ```python
  c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
  c1.metric("Rank da conta", fmt_num(linha["level"]), delta_de("level"))
  ```
  - **`st.columns(7)`** cria 7 colunas lado a lado; cada `c1..c7` é uma coluna onde a gente
    põe coisas. É assim que se faz layout horizontal no Streamlit. (Eram 6; virou 7 quando
    a gente separou "Missões concluídas" de "Partidas jogadas" — ver seção 4.2.)
  - **`.metric(rótulo, valor, delta)`** desenha aquele cartão com número grande e uma
    **setinha** de variação (o 3º argumento). Se o delta é positivo aparece verde ↑, negativo
    vermelho ↓, e se é `None` não aparece seta.
  - **`delta_de(coluna)`** (função definida no corpo) calcula a variação vs. a foto anterior.
    A lógica de "achar a foto anterior" usa filtro de DataFrame: `snaps[snaps["id"] < snap_id]`
    pega todas as fotos com id menor, e `.iloc[-1]` pega a última delas (a imediatamente
    anterior). Se não existe anterior, o delta é `None` (nada de seta).
- **As abas:**
  ```python
  aba_especies, aba_tempo, aba_desde, aba_tabela = st.tabs(["🐛 Por espécie", ...])
  with aba_especies:
      st.altair_chart(grafico_barras_especies(kills, top_n), width='stretch')
  ```
  - **`st.tabs([...])`** cria abas clicáveis e devolve um objeto por aba; o conteúdo de cada
    uma vai dentro de `with aba_x:`.
  - **`st.altair_chart(grafico, width='stretch')`** joga um gráfico Altair na tela.
    `width='stretch'` = "ocupe a largura toda do container". (Antigamente isso era
    `use_container_width=True`; o Streamlit renomeou. Se um dia der aviso de depreciação, é
    aqui que se ajusta.)
  - **Aba Evolução** só faz sentido com 2+ fotos, então tem `if len(snaps) < 2:` mostrando
    um aviso amigável. Com histórico, desenha 4 linhas (kills, créditos, rank, tempo) em
    duas fileiras de `st.columns(2)`.
  - **Aba Tabela:** **`st.text_input("🔎 Buscar espécie")`** é a caixa de busca; filtro o
    DataFrame com `tabela[tabela["Espécie"].str.contains(busca, case=False)]`.
    **`st.dataframe(...)`** mostra a planilha interativa (dá pra ordenar clicando na coluna).
    **`st.download_button(...)`** gera o CSV na hora com `tabela.to_csv(...).encode("utf-8")`
    e oferece pra baixar — bom pro portfólio (mostra que você pensou em exportar dados).

### 11.8 Sintaxe do Streamlit que usei — tabela de consulta rápida

| Função | O que faz | Como reusar |
|---|---|---|
| `st.set_page_config(...)` | título/ícone/layout da aba | 1ª chamada `st.*`; `layout="wide"` p/ tela cheia |
| `st.title` / `st.subheader` / `st.header` / `st.caption` | textos de tamanhos diferentes | passe uma string; aceita markdown |
| `st.markdown(txt, unsafe_allow_html=True)` | texto rico / injetar CSS | com `unsafe_allow_html` aceita HTML cru |
| `st.write` | "canivete suíço" que mostra quase tudo | `st.write(qualquer_coisa)` |
| `st.metric(rótulo, valor, delta)` | cartão de número com seta | 3º arg é a variação (opcional) |
| `st.columns(n)` | n colunas lado a lado | `c1,c2 = st.columns(2)`; use `c1.algo(...)` |
| `st.tabs([...])` | abas | conteúdo dentro de `with aba:` |
| `st.sidebar` | barra lateral | `with st.sidebar:` |
| `st.button(txt)` | botão; `True` no clique | sempre dentro de `if st.button(...):` |
| `st.selectbox` / `st.slider` / `st.text_input` | widgets de entrada | o retorno é o valor escolhido |
| `st.altair_chart(g, width='stretch')` | desenha gráfico Altair | `width='stretch'` = largura total |
| `st.dataframe(df)` | tabela interativa | `column_config=` p/ formatar colunas |
| `st.download_button` | baixar um arquivo | passe bytes + `file_name` + `mime` |
| `st.spinner("...")` | "carregando" | `with st.spinner("..."):` em volta do trabalho |
| `st.info` / `st.warning` / `st.success` | caixinhas coloridas de aviso | passe a mensagem |
| `st.session_state` | memória entre re-runs | é um dict: `st.session_state["chave"]` |
| `st.rerun()` | re-roda o script já | use após mudar estado que a tela deve refletir |
| `st.stop()` | encerra o script aqui | "return cedo" quando não há o que mostrar |

### 11.9 Como fazer as edições mais comuns (receitas)

- **Adicionar uma métrica nova no cabeçalho:** aumente o número em `st.columns(N)` e
  acrescente uma linha `cX.metric("Rótulo", fmt_num(linha["coluna_do_banco"]), delta_de("coluna_do_banco"))`.
  Só funciona se a coluna existir na tabela `snapshots`.
- **Mudar a cor de destaque (laranja) do painel inteiro:** troque `primaryColor` no
  `config.toml` **e** a constante `COR_LARANJA` / a lista `RAMP_LARANJA` no `dashboard.py`
  (config = componentes; constantes = gráficos).
- **Mostrar mais/menos espécies por padrão:** o `20` em `st.slider("...", 5, 77, 20)` é o
  valor inicial; o `5` e o `77` são os limites.
- **Adicionar um gráfico de evolução de outra métrica:** dentro da aba Evolução, chame
  `st.altair_chart(grafico_evolucao(snaps, "coluna", "Título", "#cor"), width='stretch')`.
- **Trocar as abas de ordem/nome:** mexa na lista passada pro `st.tabs([...])` (lembre de
  renomear as variáveis que recebem o retorno também).

### 11.10 Gotchas específicos do dashboard (pra não tropeçar)

- **`streamlit run dashboard.py`, nunca `python dashboard.py`.** Rodar com `python` direto
  dispara avisos "missing ScriptRunContext" e não abre o site — o Streamlit precisa do
  próprio launcher. (O `.bat` já faz certo.)
- **Mudou o `config.toml`? Reinicie** o `streamlit run` (Ctrl+C e rode de novo). O tema só
  é lido na inicialização. Já mudanças no `.py` recarregam sozinhas (tem um botão "Rerun").
- **`st.button` não "fica apertado".** Ele é `True` só no re-run do clique. Não dá pra fazer
  `x = st.button(...)` e checar `x` várias telas depois — pra lembrar de algo, use
  `st.session_state`.
- **Tipos no Altair (`:N`, `:Q`, `:T`) importam.** Marcar um número como `:N` faz o Altair
  tratar cada valor como categoria e o eixo sai errado. Data tem que ser `:T`.
- **O painel só LÊ o banco; quem escreve é o `snapshot.py`** (ou o botão que chama ele).
  Se os dados parecem velhos, é porque falta tirar foto nova — clique em 📸 Atualizar agora.
- **A pasta precisa ter tudo junto:** `dashboard.py`, `snapshot.py`, `drg_save_parser.py`,
  `all_drg_enemies.json`, `drg_stats.db` e a pasta `.streamlit/`. O `import snapshot` do
  painel depende dos outros `.py` estarem lá do lado.
