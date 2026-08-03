# 🪨 DRG Stats Tracker

> Extrai suas estatísticas de **Deep Rock Galactic** direto do arquivo de save (formato
> binário cru), guarda um **histórico** num banco local e mostra tudo num **dashboard**
> interativo — com ranking de kills por espécie, evolução no tempo e progresso de
> overclocks. Captura automática enquanto você joga. **Rock and Stone!** ⛏️

Um projeto que percorre o arco completo de um trabalho de dados de verdade:
**Extrair** (engenharia reversa de um save binário) → **Transformar/Armazenar** (ETL num
SQLite) → **Visualizar** (dashboard). O jogo guarda essas estatísticas, mas só mostra uma
de cada vez, sem histórico e sem gráfico. Este projeto resolve isso.

---

## ✨ O que ele faz

- 🐛 **Kills por espécie** — ranking das 77 espécies do bestiário, do save.
- 📈 **Evolução no tempo** — kills, créditos, rank e tempo de jogo ao longo dos dias.
- ⚙️ **Progresso de overclocks** — quantos você forjou de cada arma (ex.: `100/160`) e a
  lista exata do que falta.
- 🆕 **"Desde a última foto"** — o que cresceu de um dia pro outro.
- 📸 **Captura automática** — um "vigia" tira uma foto sozinho quando você joga (abre a
  missão / termina / fecha o jogo), sem você abrir terminal nenhum.
- 🗂️ **Tabela + export CSV** — busca por espécie e download dos dados.

---

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

---

## 🚀 Começando (qualquer PC, pouca configuração)

**Pré-requisito:** [Python 3.10+](https://www.python.org/downloads/) instalado (marque
"Add Python to PATH" no instalador do Windows).

```bash
# 1. Clone o repositório
git clone https://github.com/<seu-usuario>/drg-stats-tracker.git
cd drg-stats-tracker

# 2. Tire a primeira foto (acha o save sozinho e cria o banco)
python snapshot.py

# 3. Abra o painel
#    Windows: duplo clique em "Abrir Dashboard.bat"
#    Qualquer SO (manual):
pip install streamlit
streamlit run dashboard.py
```

Só o `dashboard.py` precisa de biblioteca externa (**Streamlit**; o pandas e o altair vêm
junto). O parser, o snapshot e o watcher rodam com **Python puro**.

> O save é encontrado automaticamente em **qualquer drive** (o `find_save` lê o registro
> da Steam + o `libraryfolders.vdf`). Se você usa a versão **Game Pass/Microsoft Store**,
> aponte o save com a variável de ambiente `DRG_SAVE` ou passando o caminho como argumento.

---

## 🤖 Captura automática (o pulo do gato)

Pra não precisar tirar foto na mão, o **vigia** (`watcher.py`) sobe junto com o jogo pela
Steam e tira fotos sozinho (na abertura, no fim de missão e ao fechar).

1. Rode **`configurar_steam.bat`** (duplo clique) — ele monta a linha com o caminho do seu
   PC e **copia pro clipboard**.
2. Na Steam: **DRG → Propriedades → Geral → Opções de Inicialização** → cole com `Ctrl+V`.
3. Clique em **▶ Jogar**. Pronto — o histórico se enche sozinho.

O banco não incha: se nada mudou, não grava (dedup); e guarda no máximo **uma foto por
dia** (atualizada pro estado do fim do dia), então o comparativo dia-a-dia fica limpo.

> **Por que não é um mod do mod.io?** Os mods de DRG rodam numa sandbox de Blueprint
> fechada (sem acesso a arquivos, processos ou rede). Só código nativo escaparia disso,
> o que seria pesado e frágil. Por isso a captura é externa (o vigia), não um mod.

---

## 🧠 Como a engenharia reversa funciona

O save é um arquivo **GVAS** (formato binário da Unreal Engine): ~1,4 milhão de bytes crus,
sem manual. Descobrir o significado de cada pedaço foi feito na mão.

👉 **A explicação completa, do zero absoluto (byte por byte), está em
[`logica.md`](logica.md)** — vale a leitura mesmo se você nunca programou.

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

---

## 📁 Estrutura do projeto

```
drg_save_parser.py      # lê o save binário (GVAS) -> dados organizados. Só stdlib.
snapshot.py             # tira a "foto" e grava no SQLite (1 por dia). Acha o save sozinho.
watcher.py              # vigia o save e chama o snapshot sozinho enquanto você joga.
dashboard.py            # painel Streamlit: kills, evolução, overclocks, tabela, CSV.
drg_watcher_launch.bat  # lançador pra Steam (sobe o vigia + o jogo).
configurar_steam.bat    # gera a linha das Launch Options e copia pro clipboard.
Abrir Dashboard.bat     # duplo clique abre o painel (instala o Streamlit na 1ª vez).
guids.json              # GUID -> overclock/cosmético (arma, nome, custo). O "catálogo".
all_drg_enemies.json    # GUID -> nome do bicho (as 77 espécies).
.streamlit/config.toml  # tema escuro "caverna" do painel.
logica.md               # a lógica da engenharia reversa explicada do zero.
CLAUDE.md               # o "mapa" técnico completo do projeto (decisões, gotchas, aulas).
drg_stats.db            # o banco (gerado; fora do controle de versão).
```

---

## ⚠️ Limitações conhecidas

- **Cosméticos** ainda são **estimativa**: o desbloqueio de vanity no DRG tem várias fontes
  e a contagem atual pode ficar abaixo do real. Overclocks, esse sim, está confiável.
- Alguns nomes de bichos foram deduzidos por eliminação; e 4 pares com contagem idêntica
  têm pareamento ambíguo (detalhes no `CLAUDE.md`).
- Save da versão **Game Pass/Microsoft Store** não é auto-detectado (use `DRG_SAVE`).

---

## 🛠️ Feito com

Python (stdlib: `struct`, `sqlite3`, `pathlib`…) · **SQLite** · **Streamlit** · **Altair**
· **pandas**. Nenhuma dependência pra ler o save — só Python puro.

---

## 📜 Aviso

Projeto de fã, **não oficial** e **sem afiliação** com a Ghost Ship Games. "Deep Rock
Galactic" e seus ativos pertencem aos seus donos. Este projeto só **lê** seu próprio save
localmente (nunca modifica o save do jogo). Use por sua conta e risco.

Rock and Stone! ⛏️🍺
