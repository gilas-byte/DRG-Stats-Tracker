# 🪨 DRG Stats Tracker

> 🇬🇧 **English** below · 🇧🇷 **Português** [mais abaixo](#-drg-stats-tracker-pt-br)

<p align="center">
  <img src="media/dashboard.gif" alt="DRG Stats Tracker dashboard: kills per species, progress over time and overclock completion" width="85%">
</p>

---

> Pulls your **Deep Rock Galactic** stats straight from the raw binary save file, keeps a
> **history** in a local SQLite database, and shows everything in an interactive
> **dashboard** — kills per enemy species, progress over time, and overclock completion.
> Captures automatically while you play. **Rock and Stone!** ⛏️

A project that walks the full arc of a real data job: **Extract** (reverse-engineering a
binary save) → **Transform/Load** (an ETL into SQLite) → **Visualize** (a dashboard). The
game stores these stats but only shows one at a time, with no history and no charts. This
fixes that.

## ✨ What it does

- 🐛 **Kills per species** — a ranking of the 77 bestiary species, straight from the save.
- 📈 **Progress over time** — kills, credits, rank and playtime across days.
- ⚙️ **Overclock progress** — how many you've forged per weapon (e.g. `100/160`) and the
  exact list of what's missing.
- 🆕 **"Since last snapshot"** — what grew from one day to the next.
- 📸 **Automatic capture** — a "watcher" takes a snapshot on its own while you play (mission
  start / end / game close), no terminal needed.
- 🗂️ **Table + CSV export** — search by species and download the data.

<p align="center">
  <img src="media/overclocks.gif" alt="Overclocks tab: 100/160 forged, per-weapon progress bars and the missing list" width="80%">
  <br><em>The ⚙️ Overclocks tab — completion per weapon and exactly what's left to forge.</em>
</p>

## 🧩 How the pieces connect

```
   game save             translate bytes         store history            show it nicely
 (XXXXX_Player.sav)  ->  drg_save_parser.py  ->     snapshot.py       ->     dashboard.py
        │                       │                        │                        │
        │                       │                   drg_stats.db  <──────────────-┘
        │                       │                  (SQLite database)   (reads the db)
        │                  guids.json /                   ▲
        │              all_drg_enemies.json               │
        └──────────────────────────────────── watcher.py (snapshots on its own while you play)
```

- **`drg_save_parser.py`** reads the binary save (no external dependencies).
- **`snapshot.py`** uses the parser to take a "snapshot" and store it (one per day).
- **`watcher.py`** watches the save and calls the snapshot on its own while you play.
- **`dashboard.py`** reads the database (and the save, for overclocks) and draws the charts.
- **`guids.json` / `all_drg_enemies.json`** translate the internal codes (GUIDs) into names.

## 🚀 Getting started (any PC, little configuration)

**Requirement:** [Python 3.10+](https://www.python.org/downloads/) installed (tick "Add
Python to PATH" in the Windows installer).

```bash
# 1. Clone the repository
git clone https://github.com/gilas-byte/drg-stats-tracker.git
cd drg-stats-tracker

# 2. Take the first snapshot (finds the save on its own and creates the database)
python snapshot.py

# 3. Open the dashboard
#    Windows: double-click "abrir_dashboard.bat"
#    Any OS (manual):
pip install streamlit
streamlit run dashboard.py
```

<p align="center">
  <img src="media/first-run.gif" alt="Double-clicking abrir_dashboard.bat opens the dashboard in the browser" width="80%">
  <br><em>First run — double-click <code>abrir_dashboard.bat</code> and the panel opens.</em>
</p>

Only `dashboard.py` needs an external library (**Streamlit**; pandas and altair come with
it). The parser, the snapshot and the watcher run on **pure Python**.

> The save is found automatically on **any drive** (`find_save` reads the Steam registry +
> `libraryfolders.vdf`). On the **Game Pass/Microsoft Store** version, point to the save
> with the `DRG_SAVE` environment variable or by passing the path as an argument.

## 🤖 Automatic capture

So you never snapshot by hand, the **watcher** (`watcher.py`) launches alongside the game
via Steam and snapshots on its own (on open, on mission end, on close).

1. Run **`configurar_steam.bat`** (double-click) — it builds the line with your PC's path
   and **copies it to the clipboard**.
2. In Steam: **DRG → Properties → General → Launch Options** → paste with `Ctrl+V`.
3. Click **▶ Play**. Done — the history fills up on its own.

<p align="center">
  <img src="media/steam-setup.gif" alt="Running configurar_steam.bat and pasting the line into Steam's Launch Options" width="80%">
  <br><em>Setup — run <code>configurar_steam.bat</code>, then paste into Steam → Launch Options.</em>
</p>

The database stays small: if nothing changed, it doesn't write (dedup); and it keeps at
most **one snapshot per day** (updated to the end-of-day state), so the day-to-day
comparison stays clean.

> **Why not a mod.io mod?** DRG mods run in a locked Blueprint sandbox (no file, process,
> or network access). Only native code could escape that, which would be heavy and fragile.
> So the capture is external (the watcher), not a mod.

## 🔄 Keeping it updated

When this repository gets new code, updating is one step — and it **never touches your
data**: the database (`drg_stats.db`), the log and the `.sav` files are gitignored, so your
history and snapshots survive the update untouched.

- **Windows:** double-click **`atualizar.bat`** — it runs `git pull` for you.
- **Any OS (manual):** `git pull`

The dashboard also **checks on its own**: when a newer version exists on GitHub, a
**🔔 update available** notice appears in the sidebar (checked at most once per hour).

> **Requirements:** [Git](https://git-scm.com/downloads) installed, and the project obtained
> via `git clone` (see [Getting started](#-getting-started-any-pc-little-configuration)). If
> you downloaded the **ZIP**, there's no link to the repo — grab a fresh ZIP, or switch to
> `git clone` once to get updates from then on.

## 🧠 How the reverse engineering works

The save is a **GVAS** file (Unreal Engine's binary format): ~1.4 million raw bytes, no
manual. Figuring out what each chunk means was done by hand.

👉 **The full explanation, from absolute zero (byte by byte), is in
[`logica.md`](docs/logica.md)** — worth a read even if you've never programmed.

Highlights of what was decoded:
- **FString** (a length-prefixed string) and how to find properties by their **exact
  encoding**, not by substring (so `Level` doesn't match inside `RetiredCharacterLevels`).
- **`EnemiesKilled`** — a `MapProperty` of `GUID (16 bytes) → count`, 77 species.
- Enemy names were discovered by a **JOIN on the kill count** (the in-game bestiary × the
  save).
- **Rank and promotions** are **derived** (computed from the class blocks + an XP table),
  not stored.
- **"Missions Completed" (445) ≠ "Games Played" (504)** — the former lives in a
  `MissionStatsSave` block, summed per class.
- **Overclocks** (`ForgedSchematics`) cross-referenced with `guids.json` → per-weapon
  progress.

## 📁 Project structure

```
drg_save_parser.py      # reads the binary save (GVAS) -> organized data. Stdlib only.
snapshot.py             # takes the "snapshot" and stores it in SQLite (1/day). Finds the save.
watcher.py              # watches the save and calls the snapshot while you play.
dashboard.py            # Streamlit panel: kills, progress, overclocks, table, CSV.
drg_watcher_launch.bat  # Steam launcher (starts the watcher + the game).
configurar_steam.bat    # generates the Launch Options line and copies it to the clipboard.
abrir_dashboard.bat     # double-click opens the panel (installs Streamlit the first time).
atualizar.bat           # double-click updates the project (git pull); keeps your data.
guids.json              # GUID -> overclock/cosmetic (weapon, name, cost). The "catalog".
all_drg_enemies.json    # GUID -> enemy name (the 77 species).
drg_stats.db            # the database (generated; not under version control).

media/                  # GIFs used in this README.

.streamlit/
    └─ config.toml      # the dark "cave" theme of the panel.

docs/
    ├─ logica.md        # the reverse-engineering logic explained from scratch.
    └─ claude_public.md # the full technical "map" of the project (decisions, gotchas, lessons).
```

## ⚠️ Known limitations

- **Cosmetics** are still an **estimate**: vanity unlocks in DRG have several sources and
  the current count may fall short of the real one. Overclocks, though, are reliable.
- Some enemy names were deduced by elimination; and 4 pairs with identical counts have an
  ambiguous pairing (details in `claude_public.md`).
- The **Game Pass/Microsoft Store** save is not auto-detected (use `DRG_SAVE`).

## 🛠️ Built with

Python (stdlib: `struct`, `sqlite3`, `pathlib`…) · **SQLite** · **Streamlit** · **Altair**
· **pandas**. No dependency to read the save — pure Python.

## 📜 Disclaimer

A fan project, **unofficial** and **not affiliated** with Ghost Ship Games. "Deep Rock
Galactic" and its assets belong to their owners. This project only **reads** your own save
locally (it never modifies the game save). Use at your own risk.

Rock and Stone! ⛏️🍺

---
---

# 🪨 DRG Stats Tracker (PT-BR)

> Extrai suas estatísticas de **Deep Rock Galactic** direto do arquivo de save (formato
> binário cru), guarda um **histórico** num banco local e mostra tudo num **dashboard**
> interativo — com ranking de kills por espécie, evolução no tempo e progresso de
> overclocks. Captura automática enquanto você joga. **Rock and Stone!** ⛏️

Um projeto que percorre o arco completo de um trabalho de dados de verdade:
**Extrair** (engenharia reversa de um save binário) → **Transformar/Armazenar** (ETL num
SQLite) → **Visualizar** (dashboard). O jogo guarda essas estatísticas, mas só mostra uma
de cada vez, sem histórico e sem gráfico. Este projeto resolve isso.

## ✨ O que ele faz

- 🐛 **Kills por espécie** — ranking das 77 espécies do bestiário, do save.
- 📈 **Evolução no tempo** — kills, créditos, rank e tempo de jogo ao longo dos dias.
- ⚙️ **Progresso de overclocks** — quantos você forjou de cada arma (ex.: `100/160`) e a
  lista exata do que falta.
- 🆕 **"Desde a última foto"** — o que cresceu de um dia pro outro.
- 📸 **Captura automática** — um "vigia" tira uma foto sozinho quando você joga (abre a
  missão / termina / fecha o jogo), sem você abrir terminal nenhum.
- 🗂️ **Tabela + export CSV** — busca por espécie e download dos dados.

<p align="center">
  <img src="media/overclocks.gif" alt="Aba de Overclocks: 100/160 forjados, barras de progresso por arma e a lista do que falta" width="80%">
  <br><em>A aba ⚙️ Overclocks — progresso por arma e exatamente o que falta forjar.</em>
</p>

## 🧩 Como as peças se conectam

```
  save do jogo            traduz bytes           guarda histórico          mostra bonito
 (XXXXX_Player.sav)  ->  drg_save_parser.py  ->     snapshot.py       ->     dashboard.py
        │                       │                        │                        │
        │                       │                   drg_stats.db  <──────────────-┘
        │                       │                  (banco SQLite)      (lê o banco)
        │                  guids.json /                   ▲
        │              all_drg_enemies.json               │
        └──────────────────────────────────── watcher.py (tira foto sozinho ao jogar)
```

- **`drg_save_parser.py`** sabe ler o save binário (sem dependência externa).
- **`snapshot.py`** usa o parser pra tirar uma "foto" e gravar no banco (uma por dia).
- **`watcher.py`** vigia o save e chama o snapshot sozinho enquanto você joga.
- **`dashboard.py`** lê o banco (e o save, pros overclocks) e desenha os gráficos.
- **`guids.json` / `all_drg_enemies.json`** traduzem os códigos internos (GUIDs) em nomes.

## 🚀 Começando (qualquer PC, pouca configuração)

**Pré-requisito:** [Python 3.10+](https://www.python.org/downloads/) instalado (marque
"Add Python to PATH" no instalador do Windows).

```bash
# 1. Clone o repositório
git clone https://github.com/gilas-byte/drg-stats-tracker.git
cd drg-stats-tracker

# 2. Tire a primeira foto (acha o save sozinho e cria o banco)
python snapshot.py

# 3. Abra o painel
#    Windows: duplo clique em "abrir_dashboard.bat"
#    Qualquer SO (manual):
pip install streamlit
streamlit run dashboard.py
```

<p align="center">
  <img src="media/first-run.gif" alt="Duplo clique em abrir_dashboard.bat abre o painel no navegador" width="80%">
  <br><em>Primeira vez — duplo clique em <code>abrir_dashboard.bat</code> e o painel abre.</em>
</p>

Só o `dashboard.py` precisa de biblioteca externa (**Streamlit**; o pandas e o altair vêm
junto). O parser, o snapshot e o watcher rodam com **Python puro**.

> O save é encontrado automaticamente em **qualquer drive** (o `find_save` lê o registro
> da Steam + o `libraryfolders.vdf`). Se você usa a versão **Game Pass/Microsoft Store**,
> aponte o save com a variável de ambiente `DRG_SAVE` ou passando o caminho como argumento.

## 🤖 Captura automática (o pulo do gato)

Pra não precisar tirar foto na mão, o **vigia** (`watcher.py`) sobe junto com o jogo pela
Steam e tira fotos sozinho (na abertura, no fim de missão e ao fechar).

1. Rode **`configurar_steam.bat`** (duplo clique) — ele monta a linha com o caminho do seu
   PC e **copia pro clipboard**.
2. Na Steam: **DRG → Propriedades → Geral → Opções de Inicialização** → cole com `Ctrl+V`.
3. Clique em **▶ Jogar**. Pronto — o histórico se enche sozinho.

<p align="center">
  <img src="media/steam-setup.gif" alt="Rodando configurar_steam.bat e colando a linha nas Opções de Inicialização da Steam" width="80%">
  <br><em>Setup — rode <code>configurar_steam.bat</code> e cole em Steam → Opções de Inicialização.</em>
</p>

O banco não incha: se nada mudou, não grava (dedup); e guarda no máximo **uma foto por
dia** (atualizada pro estado do fim do dia), então o comparativo dia-a-dia fica limpo.

> **Por que não é um mod do mod.io?** Os mods de DRG rodam numa sandbox de Blueprint
> fechada (sem acesso a arquivos, processos ou rede). Só código nativo escaparia disso,
> o que seria pesado e frágil. Por isso a captura é externa (o vigia), não um mod.

## 🔄 Como atualizar

Quando este repositório recebe código novo, atualizar é um passo só — e **nunca mexe nos
seus dados**: o banco (`drg_stats.db`), o log e os `.sav` estão no `.gitignore`, então seu
histórico e suas fotos sobrevivem intactos à atualização.

- **Windows:** duplo clique em **`atualizar.bat`** — ele roda o `git pull` pra você.
- **Qualquer SO (manual):** `git pull`

O painel também **checa sozinho**: quando existe versão nova no GitHub, aparece um aviso
**🔔 atualização disponível** na barra lateral (verificado no máximo uma vez por hora).

> **Pré-requisitos:** [Git](https://git-scm.com/downloads) instalado, e o projeto pego via
> `git clone` (ver [Começando](#-começando-qualquer-pc-pouca-configuração)). Se você baixou
> o **ZIP**, não existe o vínculo com o repositório — baixe um ZIP novo, ou passe a usar
> `git clone` uma vez pra receber atualizações daí em diante.

## 🧠 Como a engenharia reversa funciona

O save é um arquivo **GVAS** (formato binário da Unreal Engine): ~1,4 milhão de bytes crus,
sem manual. Descobrir o significado de cada pedaço foi feito na mão.

👉 **A explicação completa, do zero absoluto (byte por byte), está em
[`logica.md`](docs/logica.md)** — vale a leitura mesmo se você nunca programou.

Destaques do que foi decifrado:
- **FString** (texto com o tamanho na frente) e como achar propriedades pela **codificação
  exata**, não por substring (pra `Level` não casar dentro de `RetiredCharacterLevels`).
- **`EnemiesKilled`** — um `MapProperty` de `GUID (16 bytes) → contagem`, 77 espécies.
- Os nomes dos bichos foram descobertos por **JOIN pela contagem de kills** (bestiário do
  jogo × save).
- **Rank e promoções** são **derivados** (calculados dos blocos de classe + tabela de XP),
  não ficam salvos.
- **"Missões concluídas" (445) ≠ "Partidas jogadas" (504)** — o primeiro vive num bloco
  `MissionStatsSave`, somado por classe.
- **Overclocks** (`ForgedSchematics`) cruzados com o `guids.json` → progresso por arma.

## 📁 Estrutura do projeto

```
drg_save_parser.py      # lê o save binário (GVAS) -> dados organizados. Só stdlib.
snapshot.py             # tira a "foto" e grava no SQLite (1 por dia). Acha o save sozinho.
watcher.py              # vigia o save e chama o snapshot sozinho enquanto você joga.
dashboard.py            # painel Streamlit: kills, evolução, overclocks, tabela, CSV.
drg_watcher_launch.bat  # lançador pra Steam (sobe o vigia + o jogo).
configurar_steam.bat    # gera a linha das Launch Options e copia pro clipboard.
abrir_dashboard.bat     # duplo clique abre o painel (instala o Streamlit na 1ª vez).
atualizar.bat           # duplo clique atualiza o projeto (git pull); preserva seus dados.
guids.json              # GUID -> overclock/cosmético (arma, nome, custo). O "catálogo".
all_drg_enemies.json    # GUID -> nome do bicho (as 77 espécies).
drg_stats.db            # o banco (gerado; fora do controle de versão).

media/                  # GIFs usados neste README.

.streamlit/
    └─ config.toml      # tema escuro "caverna" do painel.

docs/
    ├─ logica.md        # a lógica da engenharia reversa explicada do zero.
    └─ claude_public.md # o "mapa" técnico completo do projeto (decisões, gotchas, aulas).
```

## ⚠️ Limitações conhecidas

- **Cosméticos** ainda são **estimativa**: o desbloqueio de vanity no DRG tem várias fontes
  e a contagem atual pode ficar abaixo do real. Overclocks, esse sim, está confiável.
- Alguns nomes de bichos foram deduzidos por eliminação; e 4 pares com contagem idêntica
  têm pareamento ambíguo (detalhes no `claude_public.md`).
- Save da versão **Game Pass/Microsoft Store** não é auto-detectado (use `DRG_SAVE`).

## 🛠️ Feito com

Python (stdlib: `struct`, `sqlite3`, `pathlib`…) · **SQLite** · **Streamlit** · **Altair**
· **pandas**. Nenhuma dependência pra ler o save — só Python puro.

## 📜 Aviso

Projeto de fã, **não oficial** e **sem afiliação** com a Ghost Ship Games. "Deep Rock
Galactic" e seus ativos pertencem aos seus donos. Este projeto só **lê** seu próprio save
localmente (nunca modifica o save do jogo). Use por sua conta e risco.

Rock and Stone! ⛏️🍺
