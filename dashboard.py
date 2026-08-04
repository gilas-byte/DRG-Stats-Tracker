#!/usr/bin/env python3
"""
dashboard.py — the DRG Stats Tracker PANEL.

Reads the drg_stats.db database (the "snapshots" that snapshot.py has been storing)
and draws everything nicely in an interactive site: kills-per-species ranking,
progress over time, credits, playtime and "how much you killed since the last snapshot".

Built for non-devs: it has a "📸 Update now" button that reads the save and stores
a new snapshot with no terminal needed. Just open it and click.

The whole UI is bilingual (English / Português) via a language picker in the sidebar;
English is the default. All on-screen text lives in the TEXTS dictionary below.

How to open (the easy way):
    -> DOUBLE-CLICK "abrir_dashboard.bat"

How to open (the manual way):
    pip install streamlit
    streamlit run dashboard.py

Depends on: streamlit (which brings the pandas and altair we use here), plus the
project files: drg_stats.db, drg_save_parser.py, snapshot.py.
"""

import sys
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import pandas as pd
import altair as alt
import streamlit as st

# snapshot.py is part of the same project: we reuse the logic of finding the save and
# storing the snapshot, so the "Update now" button works without a terminal.
import snapshot
import drg_save_parser as drg   # to read overclocks/cosmetics straight from the current save

# ----------------------------------------------------------------------------
# PALETTE (DRG theme: industrial black + amber orange).
# The dataviz rule here: kills per species is MAGNITUDE -> a single hue, light to
# dark (sequential ramp). No rainbow. Orange matches the game.
# ----------------------------------------------------------------------------
DB_PATH = "drg_stats.db"

COR_FUNDO      = "#12100e"   # warm black (rock)
COR_SURFACE    = "#1c1917"   # cards
COR_TEXTO      = "#f5efe6"   # main text (cream)
COR_TEXTO_FRACO = "#a89f92"  # axes/labels
COR_LARANJA    = "#eb6834"   # DRG amber (highlight)
COR_LARANJA_ESC = "#8f3a18"  # dark end of the ramp
COR_GRID       = "#332e29"   # subtle grid lines

# Single-hue sequential ramp (light -> dark) for the magnitude bars.
RAMP_LARANJA = ["#f6b98f", "#f19a63", "#eb6834", "#c14f22", "#8f3a18"]


# ----------------------------------------------------------------------------
# TRANSLATIONS (all on-screen text). English default; Português second.
# Usage: T("key")  ->  the string in the currently selected language.
# `lang` and `L` (the current-language dict) are set in the APP body, before any
# UI is drawn — the chart/formatter functions read them as globals at call time.
# ----------------------------------------------------------------------------
LANGS = {"English": "en", "Português": "pt"}   # label -> code

TEXTS = {
    "en": {
        "caption": "Your Deep Rock Galactic stats — pulled from the save, with history. "
                   "Rock and Stone!",
        # empty database
        "empty_warn": "There are no **snapshots** in the database yet. Take the first one?",
        "empty_body": "The button below reads the game save and stores the first snapshot. "
                      "After that the charts show up on their own.",
        "empty_btn": "📸 Take the first snapshot",
        "reading_save": "Reading the save...",
        # atualizar_agora messages
        "msg_no_save": "❌ Couldn't find the save automatically. Run snapshot.py once, "
                       "pointing it at the path.",
        "msg_nothing": "ℹ️ Nothing changed since the last snapshot — none stored.",
        "msg_ok": "✅ New snapshot stored (snapshot #{id})! Rock and Stone! 🪨",
        # sidebar
        "sidebar_header": "⚙️ Controls",
        "lang_label": "🌐 Language / Idioma",
        "upd_available": "🔔 An update is available ({n} {word})!\n\n"
                         "Double-click **atualizar.bat** (or run `git pull`) and reopen the panel.",
        "upd_word_one": "change", "upd_word_many": "changes",
        "upd_latest": "✅ You're on the latest version",
        "update_now": "📸 Update now",
        "update_now_help": "Reads the game save and stores a new snapshot",
        "snapshot_pick": "Snapshot",
        "species_slider": "How many species to show",
        "db_count": "Snapshots in the database: **{n}**",
        "db_file": "Database: `{name}`",
        # metrics
        "summary": "📊 Summary — {when}",
        "m_rank": "Account rank",
        "m_kills": "Total kills",
        "m_credits": "Credits",
        "m_promos": "Promotions",
        "m_missions": "Missions completed",
        "m_games": "Games played",
        "m_playtime": "Playtime",
        # tabs
        "tab_species": "🐛 By species",
        "tab_time": "📈 Over time",
        "tab_ocs": "⚙️ Overclocks",
        "tab_since": "🆕 Since last snapshot",
        "tab_table": "🗂️ Table",
        # tab: species
        "top_species": "**Top {n} most-killed species** (out of {total} total)",
        # tab: over time
        "time_need_more": "There's only **one** snapshot so far. Take more (with the "
                          "**📸 Update now** button, on different days) and the progress "
                          "shows up here. History in the making! 📆",
        "time_kills": "**Total kills over time**",
        "time_credits": "**Credits over time**",
        "time_rank": "**Account rank**",
        "time_playtime": "**Playtime (seconds)**",
        # chart labels
        "ax_kills": "Kills",
        "ax_credits": "Credits",
        "ax_rank": "Rank",
        "ax_seconds": "Seconds",
        "tt_species": "Species",
        "tt_when": "When",
        # tab: overclocks
        "oc_reread": "🔄 Re-read from save",
        "oc_reread_help": "Refreshes the overclock reading straight from the save",
        "oc_no_guids": "The **guids.json** file (the overclocks/cosmetics table) is missing "
                       "from the project folder.",
        "oc_no_save": "Couldn't find the game save to read your overclocks — it has to be "
                      "reachable **on this PC**. (It works on the PC where you play.)",
        "oc_forged": "Overclocks forged",
        "oc_missing": "Left to forge",
        "oc_complete": "Collection complete",
        "oc_caption": "Full bar = the weapon's total overclocks; the orange part is how many "
                      "you've forged. The most incomplete weapons are on top.",
        "oc_expander": "📋 What's left to forge (per weapon)",
        "oc_col_class": "Class",
        "oc_col_weapon": "Weapon",
        "oc_col_havetotal": "Have/Total",
        "oc_col_missing": "Missing",
        "oc_ax": "Overclocks",
        "cos_title": "**Cosmetics** — estimate ⚠️",
        "cos_caption": "Cosmetic unlocks in DRG come from several sources; this count may be "
                       "BELOW the real one. Treat it as an estimate until we map it better.",
        "cos_col_cat": "Category",
        "cos_col_have": "Have",
        "cos_col_total": "Total",
        # tab: since last
        "since_only": "This is the oldest snapshot (or the only one). There's no previous one "
                      "to compare with. Pick a more recent snapshot in the sidebar, or take "
                      "new ones.",
        "since_compare": "**Comparing** snapshot #{a} with #{b} ({when})",
        "since_nothing": "Nothing changed between these two snapshots. 😴",
        "since_total": "New kills in this period",
        # tab: table
        "search_species": "🔎 Search species",
        "search_ph": "e.g.: Grunt, Mactera...",
        "col_species": "Species",
        "col_kills": "Kills",
        "download_csv": "⬇️ Download as CSV",
        # tab: missions & stats
        "tab_stats": "🎖️ Missions & Stats",
        "stats_no_ref": "The **mission_stats.json** file (the stats reference table) is "
                        "missing from the project folder.",
        "sec_overview": "Overview",
        "sec_secondary": "Secondary missions by type",
        "sec_biome": "Missions by biome",
        "sec_type": "Missions by type",
        "sec_class": "Missions by class",
        "sec_hazard": "Missions by hazard",
        "sec_warning": "Warnings completed",
        "sec_economy": "Economy & bar",
        "sec_forging": "Forging",
        "sec_progression": "Progression",
        "sec_misc": "Miscellaneous",
        "m_distance": "Distance travelled",
        "m_missiontime": "Mission time",
        "m_downs": "Total downs",
        "m_levelups": "Character level-ups",
        "col_stat": "Stat",
        "col_value": "Value",
        "stats_caption": "Read live from your current save and cross-referenced with the "
                         "game's own stat definitions (reverse-engineered from the .pak). "
                         "Not stored in history — it's your state right now.",
    },
    "pt": {
        "caption": "Suas estatísticas de Deep Rock Galactic — extraídas do save, com histórico. "
                   "Rock and Stone!",
        "empty_warn": "Ainda não há nenhuma **foto** no banco. Vamos tirar a primeira?",
        "empty_body": "O botão abaixo lê o save do jogo e grava a primeira foto. "
                      "Depois disso os gráficos aparecem sozinhos.",
        "empty_btn": "📸 Tirar a primeira foto",
        "reading_save": "Lendo o save...",
        "msg_no_save": "❌ Não achei o save automaticamente. Rode o snapshot.py apontando o "
                       "caminho uma vez.",
        "msg_nothing": "ℹ️ Nada mudou desde a última foto — nenhuma nova gravada.",
        "msg_ok": "✅ Foto nova gravada (snapshot #{id})! Rock and Stone! 🪨",
        "sidebar_header": "⚙️ Controles",
        "lang_label": "🌐 Language / Idioma",
        "upd_available": "🔔 Tem atualização disponível ({n} {word})!\n\n"
                         "Dê duplo clique em **atualizar.bat** (ou rode `git pull`) e reabra o painel.",
        "upd_word_one": "novidade", "upd_word_many": "novidades",
        "upd_latest": "✅ Você está na última versão",
        "update_now": "📸 Atualizar agora",
        "update_now_help": "Lê o save do jogo e grava uma foto nova",
        "snapshot_pick": "Foto (snapshot)",
        "species_slider": "Quantas espécies mostrar",
        "db_count": "Fotos no banco: **{n}**",
        "db_file": "Banco: `{name}`",
        "summary": "📊 Resumo — {when}",
        "m_rank": "Rank da conta",
        "m_kills": "Total de kills",
        "m_credits": "Créditos",
        "m_promos": "Promoções",
        "m_missions": "Missões concluídas",
        "m_games": "Partidas jogadas",
        "m_playtime": "Tempo de jogo",
        "tab_species": "🐛 Por espécie",
        "tab_time": "📈 Evolução",
        "tab_ocs": "⚙️ Overclocks",
        "tab_since": "🆕 Desde a última foto",
        "tab_table": "🗂️ Tabela",
        "top_species": "**Top {n} espécies mais mortas** (de {total} no total)",
        "time_need_more": "Só existe **uma** foto por enquanto. Tire mais fotos (com o botão "
                          "**📸 Atualizar agora**, em dias diferentes) e a evolução aparece "
                          "aqui. É o histórico se formando! 📆",
        "time_kills": "**Total de kills ao longo do tempo**",
        "time_credits": "**Créditos ao longo do tempo**",
        "time_rank": "**Rank da conta**",
        "time_playtime": "**Tempo de jogo (segundos)**",
        "ax_kills": "Kills",
        "ax_credits": "Créditos",
        "ax_rank": "Rank",
        "ax_seconds": "Segundos",
        "tt_species": "Espécie",
        "tt_when": "Quando",
        "oc_reread": "🔄 Reler do save",
        "oc_reread_help": "Atualiza a leitura de overclocks direto do save",
        "oc_no_guids": "Falta o **guids.json** (a tabela de overclocks/cosméticos) na pasta "
                       "do projeto.",
        "oc_no_save": "Não achei o save do jogo pra ler seus overclocks — ele precisa estar "
                      "acessível **neste PC**. (No PC onde você joga, funciona.)",
        "oc_forged": "Overclocks forjados",
        "oc_missing": "Faltam forjar",
        "oc_complete": "Coleção completa",
        "oc_caption": "Barra cheia = total de overclocks da arma; a parte laranja é quanto "
                      "você já forjou. As armas mais incompletas ficam no topo.",
        "oc_expander": "📋 O que falta forjar (por arma)",
        "oc_col_class": "Classe",
        "oc_col_weapon": "Arma",
        "oc_col_havetotal": "Tem/Total",
        "oc_col_missing": "Faltando",
        "oc_ax": "Overclocks",
        "cos_title": "**Cosméticos** — estimativa ⚠️",
        "cos_caption": "O desbloqueio de cosméticos no DRG vem de várias fontes; esta contagem "
                       "pode ficar ABAIXO do real. Trate como estimativa até a gente mapear melhor.",
        "cos_col_cat": "Categoria",
        "cos_col_have": "Tem",
        "cos_col_total": "Total",
        "since_only": "Esta é a foto mais antiga (ou a única). Não há uma anterior pra comparar. "
                      "Escolha uma foto mais recente na barra lateral, ou tire fotos novas.",
        "since_compare": "**Comparando** a foto #{a} com a #{b} ({when})",
        "since_nothing": "Nada mudou entre essas duas fotos. 😴",
        "since_total": "Total de kills novas nesse período",
        "search_species": "🔎 Buscar espécie",
        "search_ph": "ex.: Grunt, Mactera...",
        "col_species": "Espécie",
        "col_kills": "Kills",
        "download_csv": "⬇️ Baixar como CSV",
        # tab: missions & stats
        "tab_stats": "🎖️ Missões & Stats",
        "stats_no_ref": "Falta o **mission_stats.json** (a tabela de referência das stats) "
                        "na pasta do projeto.",
        "sec_overview": "Visão geral",
        "sec_secondary": "Missões secundárias por tipo",
        "sec_biome": "Missões por bioma",
        "sec_type": "Missões por tipo",
        "sec_class": "Missões por classe",
        "sec_hazard": "Missões por perigo",
        "sec_warning": "Warnings concluídos",
        "sec_economy": "Economia & bar",
        "sec_forging": "Forja",
        "sec_progression": "Progressão",
        "sec_misc": "Diversos",
        "m_distance": "Distância percorrida",
        "m_missiontime": "Tempo em missão",
        "m_downs": "Total de quedas",
        "m_levelups": "Level-ups de classe",
        "col_stat": "Stat",
        "col_value": "Valor",
        "stats_caption": "Lido ao vivo do seu save atual e cruzado com as definições de stat "
                         "do próprio jogo (engenharia reversa do .pak). Não é guardado no "
                         "histórico — é o seu estado de agora.",
    },
}


def T(key: str, **kw) -> str:
    """The current-language string for `key`, with optional .format() fields."""
    s = TEXTS[lang][key]
    return s.format(**kw) if kw else s


# ----------------------------------------------------------------------------
# DATABASE ACCESS
# ----------------------------------------------------------------------------
def conectar() -> sqlite3.Connection | None:
    """Open the database read-only (the panel never writes directly)."""
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def carregar_snapshots(conn) -> pd.DataFrame:
    """All snapshots, oldest -> newest. Becomes a pandas table."""
    df = pd.read_sql_query(
        "SELECT * FROM snapshots ORDER BY id ASC", conn,
    )
    if not df.empty:
        # taken_at comes as ISO text in UTC (that's how we store it — the right,
        # timezone-neutral standard). To DISPLAY, we convert to the PC's LOCAL
        # timezone (e.g. Brazil = UTC-3) and only then drop the timezone (make it
        # "naive" for Altair/strftime). datetime.now().astimezone().tzinfo grabs the
        # PC's timezone automatically — no hardcoding, works on any machine.
        fuso_local = datetime.now().astimezone().tzinfo
        df["quando"] = (pd.to_datetime(df["taken_at"], utc=True)
                        .dt.tz_convert(fuso_local)
                        .dt.tz_localize(None))
    return df


def carregar_kills(conn, snapshot_id: int) -> pd.DataFrame:
    """The per-species counts of ONE specific snapshot, highest to lowest."""
    df = pd.read_sql_query(
        """SELECT guid, name, count
           FROM kills WHERE snapshot_id = ?
           ORDER BY count DESC""",
        conn, params=(snapshot_id,),
    )
    # name may be NULL (untranslated creature). We show the start of the GUID instead.
    df["especie"] = df["name"].fillna("GUID:" + df["guid"].str.slice(0, 8))
    return df


def carregar_deltas(conn, id_atual: int, id_anterior: int) -> pd.DataFrame:
    """
    How much each species GREW between two snapshots. Note: the delta is COMPUTED
    on the fly with a JOIN — we store facts (counts), not derived values.
    """
    df = pd.read_sql_query(
        """SELECT COALESCE(k2.name, 'GUID:'||substr(k2.guid,1,8)) AS especie,
                  k2.count                        AS agora,
                  k2.count - COALESCE(k1.count, 0) AS delta
           FROM kills k2
           LEFT JOIN kills k1
                  ON k1.guid = k2.guid AND k1.snapshot_id = :ant
           WHERE k2.snapshot_id = :atu
           ORDER BY delta DESC""",
        conn, params={"ant": id_anterior, "atu": id_atual},
    )
    return df


# ----------------------------------------------------------------------------
# FORMATTERS (make a giant number readable — language-aware separators)
# ----------------------------------------------------------------------------
def fmt_num(n) -> str:
    """75466 -> '75,466' (EN) / '75.466' (PT)."""
    if n is None:
        return "—"
    s = f"{int(n):,}"                      # Python default = US style (comma)
    return s.replace(",", ".") if lang == "pt" else s


def fmt_horas(segundos) -> str:
    """Seconds -> '34.3 h' (EN) / '34,3 h' (PT)."""
    if not segundos:
        return "—"
    h = segundos / 3600
    s = f"{h:,.1f}"                        # US style: 1,234.5
    if lang == "pt":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} h"


def fmt_km(cm) -> str:
    """Centimetres -> '2,032.1 km' (EN) / '2.032,1 km' (PT)."""
    if not cm:
        return "—"
    s = f"{cm / 100000:,.1f}"              # US style
    if lang == "pt":
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} km"


def _dt_fmt() -> str:
    """Date/time pattern for the current language (PT: dd/mm, EN: mm/dd)."""
    return "%d/%m/%Y %H:%M" if lang == "pt" else "%m/%d/%Y %H:%M"


def fmt_quando(dt) -> str:
    """Friendly date/time."""
    if pd.isna(dt):
        return "—"
    return dt.strftime(_dt_fmt())


# ----------------------------------------------------------------------------
# ACTION: take a new snapshot (what snapshot.py does, but via a button)
# ----------------------------------------------------------------------------
def atualizar_agora() -> str:
    """Read the save and store a new snapshot. Returns a message for the user."""
    save_path = snapshot.find_save()
    if save_path is None or not save_path.exists():
        return T("msg_no_save")
    names = snapshot.load_names()
    conn = snapshot.conectar(DB_PATH)
    try:
        snap_id = snapshot.tirar_snapshot(conn, save_path, names)
    finally:
        conn.close()
    if snap_id is None:
        return T("msg_nothing")
    return T("msg_ok", id=snap_id)


# ----------------------------------------------------------------------------
# CHARTS (Altair)
# ----------------------------------------------------------------------------
def grafico_barras_especies(df: pd.DataFrame, top_n: int) -> alt.Chart:
    """Kills-per-species ranking — horizontal bars, orange ramp (magnitude)."""
    d = df.head(top_n).copy()
    base = alt.Chart(d).encode(
        y=alt.Y("especie:N", sort="-x", title=None,
                axis=alt.Axis(labelColor=COR_TEXTO, labelLimit=220,
                              labelFontSize=12, domainColor=COR_GRID, ticks=False)),
        x=alt.X("count:Q", title=T("ax_kills"),
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, titleColor=COR_TEXTO_FRACO,
                              gridColor=COR_GRID, format="~s")),
    )
    barras = base.mark_bar(cornerRadiusEnd=4, height=alt.RelativeBandSize(0.72)).encode(
        # color = magnitude (single-hue sequential ramp), no legend: the bar speaks for itself.
        color=alt.Color("count:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None),
        tooltip=[alt.Tooltip("especie:N", title=T("tt_species")),
                 alt.Tooltip("count:Q", title=T("ax_kills"), format=",")],
    )
    # value label right at the bar's tip (readable without hovering)
    rotulos = base.mark_text(
        align="left", dx=4, color=COR_TEXTO, fontSize=11,
    ).encode(text=alt.Text("count:Q", format=","))

    altura = max(120, len(d) * 26)
    return (barras + rotulos).properties(height=altura).configure_view(
        strokeWidth=0
    ).configure(background=COR_SURFACE)


def grafico_evolucao(df: pd.DataFrame, coluna: str, titulo: str, cor: str) -> alt.Chart:
    """Progress of one metric across snapshots — a single line over time."""
    d = df.dropna(subset=[coluna])
    linha = alt.Chart(d).mark_line(
        color=cor, strokeWidth=2, point=alt.OverlayMarkDef(color=cor, size=55),
    ).encode(
        x=alt.X("quando:T", title=None,
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, gridColor=COR_GRID)),
        y=alt.Y(f"{coluna}:Q", title=titulo,
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, titleColor=COR_TEXTO_FRACO,
                              gridColor=COR_GRID, format="~s")),
        tooltip=[alt.Tooltip("quando:T", title=T("tt_when"), format="%d/%m/%Y %H:%M"),
                 alt.Tooltip(f"{coluna}:Q", title=titulo, format=",")],
    ).properties(height=260).configure_view(strokeWidth=0).configure(background=COR_SURFACE)
    return linha


# ----------------------------------------------------------------------------
# OVERCLOCKS / COSMETICS (reads the CURRENT save + cross-refs guids.json)
# ----------------------------------------------------------------------------
# Unlike the rest of the panel (which reads the DATABASE/history), the overclock
# comparison is about the CURRENT state. So we read the save directly. Cached with
# @st.cache_data so we don't re-parse the save on every click (Streamlit re-runs the
# whole script on every interaction — see section 11.0 of CLAUDE.md).
@st.cache_data(show_spinner=False)
def carregar_guids() -> dict | None:
    """The reference table (GUID -> weapon/name). It's the 'Y' of the comparison."""
    p = Path("guids.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@st.cache_data(show_spinner=False)
def estado_do_save() -> dict | None:
    """What you HAVE: forged overclocks + cosmetics, read from the current save."""
    save = snapshot.find_save()
    if save is None or not Path(save).exists():
        return None
    s = drg.parse_save(str(save), enemy_names=snapshot.load_names())
    return {"forjados": {g.upper() for g in s["forged_schematics"]},
            "vanity":   {g.upper() for g in s["vanity_items"]}}


@st.cache_data(show_spinner=False)
def carregar_mission_stats() -> pd.DataFrame | None:
    """Every MissionStat, read from the CURRENT save + labeled via mission_stats.json.

    Like the overclocks tab, this is CURRENT state (not history), so we read the save
    live and cross-ref the reference file. Returns a DataFrame [category, label, value]
    or None if the save / reference isn't available.
    """
    ref_p = Path("mission_stats.json")
    if not ref_p.exists():
        return None
    save = snapshot.find_save()
    if save is None or not Path(save).exists():
        return None
    ref = json.loads(ref_p.read_text(encoding="utf-8"))
    stats = drg.parse_mission_stats(Path(save).read_bytes())
    linhas = [{"category": ref[g]["category"], "label": ref[g]["label"], "value": v}
              for g, v in stats.items() if g in ref]
    return pd.DataFrame(linhas)


def grafico_categoria(df: pd.DataFrame, category: str) -> alt.Chart:
    """Reuse the species-bar chart for one stat category (label -> especie, value -> count)."""
    d = (df[df["category"] == category][["label", "value"]]
         .rename(columns={"label": "especie", "value": "count"})
         .sort_values("count", ascending=False))
    return grafico_barras_especies(d, len(d))


def tabela_overclocks(ref: dict, forjados: set) -> pd.DataFrame:
    """Per weapon: how many overclocks you have, the total, and the missing list."""
    total, tem, faltam, classe = defaultdict(int), defaultdict(int), defaultdict(list), {}
    for guid, meta in ref["Weapons"].items():
        arma = meta["weapon"]
        classe[arma] = meta.get("dwarf", "?")
        total[arma] += 1
        if guid.upper() in forjados:
            tem[arma] += 1
        else:
            faltam[arma].append(meta["name"])
    linhas = [{
        "arma": a, "classe": classe[a], "tem": tem[a], "total": total[a],
        "faltam_n": total[a] - tem[a], "pct": tem[a] / total[a],
        "rotulo": f"{tem[a]}/{total[a]}",
        "faltando": ", ".join(sorted(faltam[a])) or ("— completo!" if lang == "pt"
                                                      else "— complete!"),
    } for a in total]
    return pd.DataFrame(linhas).sort_values(["pct", "arma"])


def grafico_overclocks(df: pd.DataFrame) -> alt.Chart:
    """Progress bar per weapon: background = total, orange = how many you have."""
    altura = max(160, len(df) * 28)
    base = alt.Chart(df).encode(
        y=alt.Y("arma:N", sort=alt.EncodingSortField("pct", order="ascending"),
                title=None,
                # labelLimit high enough to show the FULL weapon name (e.g.
                # "'Lead Storm' Powered Minigun") — the default truncates to "...Pow"
                # and made the nickname look like an overclock name.
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, labelLimit=260)),
    )
    fundo = base.mark_bar(color=COR_GRID, cornerRadiusEnd=3,
                          height=alt.RelativeBandSize(0.68)).encode(
        x=alt.X("total:Q", title=T("oc_ax"),
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, tickMinStep=1)),
    )
    frente = base.mark_bar(cornerRadiusEnd=3, height=alt.RelativeBandSize(0.68)).encode(
        x=alt.X("tem:Q"),
        color=alt.Color("pct:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None),
        tooltip=[alt.Tooltip("arma:N", title=T("oc_col_weapon")),
                 alt.Tooltip("classe:N", title=T("oc_col_class")),
                 alt.Tooltip("rotulo:N", title=T("oc_col_havetotal")),
                 alt.Tooltip("faltando:N", title=T("oc_col_missing"))],
    )
    rotulo = base.mark_text(align="left", dx=5, color=COR_TEXTO).encode(
        x=alt.X("total:Q"), text="rotulo:N",
    )
    return ((fundo + frente + rotulo).properties(height=altura)
            .configure_view(strokeWidth=0)
            .configure_axis(grid=False, domainColor=COR_GRID)
            .configure(background=COR_SURFACE))


# ============================================================================
# APPLICATION
# ============================================================================
st.set_page_config(page_title="DRG Stats Tracker", page_icon="🪨", layout="wide")

# --- language: decided BEFORE any UI is drawn -------------------------------
# The picker widget lives in the sidebar (rendered further down), but it writes to
# st.session_state["_lang_label"] with a key. On the rerun a change triggers, that
# value is already updated when we read it here at the top — so the WHOLE page
# (title included) reflects the chosen language. English is the default.
st.session_state.setdefault("_lang_label", "English")
lang = LANGS[st.session_state["_lang_label"]]   # global, read by T()/fmt_*/charts

# --- a dark, cave-style theme via CSS (Streamlit lets you inject it) ---
st.markdown(f"""
<style>
    .stApp {{ background: {COR_FUNDO}; }}
    h1, h2, h3, h4 {{ color: {COR_TEXTO}; }}
    [data-testid="stMetricValue"] {{ color: {COR_LARANJA}; font-weight: 700; }}
    [data-testid="stMetricLabel"] {{ color: {COR_TEXTO_FRACO}; }}
    [data-testid="stMetric"] {{
        background: {COR_SURFACE}; border: 1px solid {COR_GRID};
        border-radius: 12px; padding: 14px 16px;
    }}
    section[data-testid="stSidebar"] {{ background: {COR_SURFACE}; }}
    .stDataFrame {{ border-radius: 10px; }}
</style>
""", unsafe_allow_html=True)

st.title("🪨 DRG Stats Tracker")
st.caption(T("caption"))

conn = conectar()

# --- Case 1: database doesn't exist yet / is empty -------------------------
if conn is None or carregar_snapshots(conn).empty:
    st.warning(T("empty_warn"))
    st.write(T("empty_body"))
    if st.button(T("empty_btn"), type="primary"):
        with st.spinner(T("reading_save")):
            msg = atualizar_agora()
        st.info(msg)
        st.rerun()
    st.stop()

snaps = carregar_snapshots(conn)

# --------------------------- UPDATE CHECK ----------------------------------
# Windows: keep the git subprocess from flashing a console window (see CLAUDE.md
# gotcha). On other OSes the flag is 0 (no-op).
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0


@st.cache_data(ttl=3600)   # ask GitHub at most once per hour (fetch is the slow bit)
def checar_atualizacao() -> dict:
    """Ask GitHub (via git) whether there's a newer version of the project.

    Returns {"estado": "desatualizado"|"atualizado"|"indisponivel", "atras": N}.
    Fails SILENTLY ("indisponivel") when git is missing, this isn't a git clone
    (a ZIP download), or there's no network — the panel must never scare the user.
    """
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=Path(__file__).parent,
            capture_output=True, text=True, timeout=10,
            creationflags=_SEM_JANELA,
        )
    try:
        # Is this folder a git clone at all? (ZIP downloads are not.)
        r = git("rev-parse", "--is-inside-work-tree")
        if r.returncode != 0 or r.stdout.strip() != "true":
            return {"estado": "indisponivel"}
        # Download the newest refs from GitHub (info only — no merge, no file change).
        if git("fetch", "--quiet").returncode != 0:
            return {"estado": "indisponivel"}   # no network / no remote
        # Which branch do we track? (usually origin/main)
        up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        upstream = up.stdout.strip() if up.returncode == 0 else "origin/main"
        # How many commits is our local copy BEHIND the remote?
        cnt = git("rev-list", "--count", f"HEAD..{upstream}")
        if cnt.returncode != 0:
            return {"estado": "indisponivel"}
        atras = int(cnt.stdout.strip() or 0)
        return {"estado": "desatualizado" if atras else "atualizado", "atras": atras}
    except Exception:
        return {"estado": "indisponivel"}


# --------------------------- SIDEBAR ---------------------------------------
with st.sidebar:
    st.header(T("sidebar_header"))

    # Language picker (writes st.session_state["_lang_label"]; read at the top).
    st.selectbox(T("lang_label"), list(LANGS.keys()), key="_lang_label")

    # Update notification: warns (once/hour) when the GitHub repo has newer code.
    _upd = checar_atualizacao()
    if _upd["estado"] == "desatualizado":
        _n = _upd["atras"]
        _word = T("upd_word_one") if _n == 1 else T("upd_word_many")
        st.warning(T("upd_available", n=_n, word=_word))
    elif _upd["estado"] == "atualizado":
        st.caption(T("upd_latest"))

    if st.button(T("update_now"), type="primary", width='stretch',
                 help=T("update_now_help")):
        with st.spinner(T("reading_save")):
            msg = atualizar_agora()
        st.session_state["_msg_atualizar"] = msg
        st.rerun()
    if "_msg_atualizar" in st.session_state:
        st.info(st.session_state.pop("_msg_atualizar"))

    st.divider()

    # Choose which snapshot to view (default = the most recent one).
    opcoes = {
        f"#{r.id} — {fmt_quando(r.quando)}": int(r.id)
        for r in snaps.iloc[::-1].itertuples()   # newest on top
    }
    escolha = st.selectbox(T("snapshot_pick"), list(opcoes.keys()))
    snap_id = opcoes[escolha]

    top_n = st.slider(T("species_slider"), 5, 77, 20, step=1)

    st.divider()
    st.caption(T("db_count", n=len(snaps)))
    st.caption(T("db_file", name=Path(DB_PATH).resolve().name))

# --------------------------- HEADER (metrics) ------------------------------
linha = snaps[snaps["id"] == snap_id].iloc[0]

# if there's a previous snapshot, we compute the "deltas" to show a variation arrow
anteriores = snaps[snaps["id"] < snap_id]
tem_anterior = not anteriores.empty
linha_ant = anteriores.iloc[-1] if tem_anterior else None

def delta_de(coluna):
    if not tem_anterior or pd.isna(linha[coluna]) or pd.isna(linha_ant[coluna]):
        return None
    d = linha[coluna] - linha_ant[coluna]
    return None if d == 0 else fmt_num(d)

st.subheader(T("summary", when=fmt_quando(linha['quando'])))

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric(T("m_rank"), fmt_num(linha["level"]), delta_de("level"))
c2.metric(T("m_kills"), fmt_num(linha["total_kills"]), delta_de("total_kills"))
c3.metric(T("m_credits"), fmt_num(linha["credits"]), delta_de("credits"))
c4.metric(T("m_promos"), fmt_num(linha["times_retired"]), delta_de("times_retired"))
# Missions COMPLETED (what the game shows, e.g. 445) != Games PLAYED
# (NumberOfGamesPlayed, e.g. 504, includes aborted/failed ones). Distinct stats.
c5.metric(T("m_missions"), fmt_num(linha["missions_completed"]), delta_de("missions_completed"))
c6.metric(T("m_games"), fmt_num(linha["games_played"]), delta_de("games_played"))
c7.metric(T("m_playtime"), fmt_horas(linha["playtime_seconds"]))

st.divider()

# --------------------------- TABS ------------------------------------------
aba_especies, aba_tempo, aba_ocs, aba_stats, aba_desde, aba_tabela = st.tabs(
    [T("tab_species"), T("tab_time"), T("tab_ocs"), T("tab_stats"),
     T("tab_since"), T("tab_table")]
)

kills = carregar_kills(conn, snap_id)

# ---- Tab 1: ranking by species ----
with aba_especies:
    st.markdown(T("top_species", n=min(top_n, len(kills)), total=len(kills)))
    st.altair_chart(grafico_barras_especies(kills, top_n), width='stretch')

# ---- Tab 2: progress over time ----
with aba_tempo:
    if len(snaps) < 2:
        st.info(T("time_need_more"))
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(T("time_kills"))
            st.altair_chart(grafico_evolucao(snaps, "total_kills", T("ax_kills"), COR_LARANJA),
                            width='stretch')
        with col_b:
            st.markdown(T("time_credits"))
            st.altair_chart(grafico_evolucao(snaps, "credits", T("ax_credits"), "#eda100"),
                            width='stretch')
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown(T("time_rank"))
            st.altair_chart(grafico_evolucao(snaps, "level", T("ax_rank"), "#1baf7a"),
                            width='stretch')
        with col_d:
            st.markdown(T("time_playtime"))
            st.altair_chart(grafico_evolucao(snaps, "playtime_seconds", T("ax_seconds"), "#e87ba4"),
                            width='stretch')

# ---- Tab 3: overclocks (and cosmetics) ----
with aba_ocs:
    if st.button(T("oc_reread"), help=T("oc_reread_help")):
        estado_do_save.clear()
        carregar_guids.clear()
        st.rerun()

    ref = carregar_guids()
    estado = estado_do_save()
    if ref is None:
        st.warning(T("oc_no_guids"))
    elif estado is None:
        st.warning(T("oc_no_save"))
    else:
        oc = tabela_overclocks(ref, estado["forjados"])
        tem_t, tot_t = int(oc["tem"].sum()), int(oc["total"].sum())
        m1, m2, m3 = st.columns(3)
        m1.metric(T("oc_forged"), f"{tem_t}/{tot_t}")
        m2.metric(T("oc_missing"), fmt_num(tot_t - tem_t))
        m3.metric(T("oc_complete"), f"{tem_t / tot_t * 100:.0f}%")
        st.progress(tem_t / tot_t)
        st.altair_chart(grafico_overclocks(oc), width='stretch')
        st.caption(T("oc_caption"))

        with st.expander(T("oc_expander")):
            faltantes = (oc[oc["faltam_n"] > 0][["classe", "arma", "rotulo", "faltando"]]
                         .rename(columns={"classe": T("oc_col_class"), "arma": T("oc_col_weapon"),
                                          "rotulo": T("oc_col_havetotal"),
                                          "faltando": T("oc_col_missing")}))
            st.dataframe(faltantes.reset_index(drop=True), width='stretch', hide_index=True)

        # --- cosmetics: honest about the uncertainty (see section 4.2/5 of CLAUDE.md) ---
        st.divider()
        st.markdown(T("cos_title"))
        st.caption(T("cos_caption"))
        possui = estado["vanity"] | estado["forjados"]   # vanity + the matrix-core forged ones
        cos = [{T("cos_col_cat"): cat.replace("Cosmetic - ", ""),
                T("cos_col_have"): sum(1 for g in ref[cat] if g.upper() in possui),
                T("cos_col_total"): len(ref[cat])}
               for cat in ["Cosmetic - Headwear", "Cosmetic - Moustache", "Cosmetic - Beard",
                           "Cosmetic - Sideburns", "Victory Moves", "Weapon Skins"] if cat in ref]
        st.dataframe(pd.DataFrame(cos), width='stretch', hide_index=True)

# ---- Tab 4: missions & stats (95 stats read live from the save) ----
with aba_stats:
    if st.button(T("oc_reread"), help=T("oc_reread_help"), key="reread_stats"):
        carregar_mission_stats.clear()
        st.rerun()
    ms = carregar_mission_stats()
    if ms is None:
        if not Path("mission_stats.json").exists():
            st.warning(T("stats_no_ref"))
        else:
            st.warning(T("oc_no_save"))
    else:
        st.caption(T("stats_caption"))
        val_de = dict(zip(ms["label"], ms["value"]))   # label -> value lookup

        # --- Overview tiles (special formatting for distance/time) ---
        st.markdown("### " + T("sec_overview"))
        o1, o2, o3, o4, o5, o6 = st.columns(6)
        o1.metric(T("m_kills"), fmt_num(val_de.get("Enemies Killed")))
        o2.metric("Minerals", fmt_num(val_de.get("Minerals Mined")))
        # distance is stored in cm -> show km
        o3.metric(T("m_distance"), fmt_km(val_de.get("Distance Travelled")))
        o4.metric(T("m_missiontime"), fmt_horas(val_de.get("Mission Time")))
        o5.metric(T("m_downs"), fmt_num(val_de.get("Total Downs")))
        o6.metric(T("m_levelups"), fmt_num(val_de.get("Character Level-Ups")))

        # --- the bar charts the user asked for ---
        st.markdown("### " + T("sec_secondary"))
        st.altair_chart(grafico_categoria(ms, "Secondary"), width='stretch')

        st.markdown("### " + T("sec_biome"))
        st.altair_chart(grafico_categoria(ms, "Biome"), width='stretch')

        st.markdown("### " + T("sec_type"))
        st.altair_chart(grafico_categoria(ms, "Mission Type"), width='stretch')

        col_cl, col_hz = st.columns(2)
        with col_cl:
            st.markdown("### " + T("sec_class"))
            st.altair_chart(grafico_categoria(ms, "Class"), width='stretch')
        with col_hz:
            st.markdown("### " + T("sec_hazard"))
            st.altair_chart(grafico_categoria(ms, "Hazard"), width='stretch')

        st.markdown("### " + T("sec_warning"))
        st.altair_chart(grafico_categoria(ms, "Warning"), width='stretch')

        # --- the remaining scalar categories as compact tables ---
        def tabela_cat(category):
            t = (ms[ms["category"] == category][["label", "value"]]
                 .sort_values("value", ascending=False)
                 .rename(columns={"label": T("col_stat"), "value": T("col_value")}))
            t[T("col_value")] = t[T("col_value")].map(fmt_num)
            return t.reset_index(drop=True)

        cA, cB, cC = st.columns(3)
        for coluna, cat, titulo in [(cA, "Economy", "sec_economy"),
                                    (cB, "Forging", "sec_forging"),
                                    (cC, "Progression", "sec_progression")]:
            with coluna:
                st.markdown("**" + T(titulo) + "**")
                st.dataframe(tabela_cat(cat), width='stretch', hide_index=True)
        if not ms[ms["category"] == "Misc"].empty:
            st.markdown("**" + T("sec_misc") + "**")
            st.dataframe(tabela_cat("Misc"), width='stretch', hide_index=True)


# ---- Tab 5: what grew since the previous snapshot ----
with aba_desde:
    if not tem_anterior:
        st.info(T("since_only"))
    else:
        st.markdown(T("since_compare", a=snap_id, b=int(linha_ant['id']),
                      when=fmt_quando(linha_ant['quando'])))
        deltas = carregar_deltas(conn, snap_id, int(linha_ant["id"]))
        cresceram = deltas[deltas["delta"] > 0]
        if cresceram.empty:
            st.write(T("since_nothing"))
        else:
            total_novo = int(cresceram["delta"].sum())
            st.metric(T("since_total"), fmt_num(total_novo))
            g = grafico_barras_especies(
                cresceram.rename(columns={"delta": "count"}), min(top_n, len(cresceram))
            )
            st.altair_chart(g, width='stretch')

# ---- Tab 5: raw table (with search) ----
with aba_tabela:
    busca = st.text_input(T("search_species"), placeholder=T("search_ph"))
    tabela = kills[["especie", "count"]].rename(
        columns={"especie": T("col_species"), "count": T("col_kills")})
    if busca:
        tabela = tabela[tabela[T("col_species")].str.contains(busca, case=False, na=False)]
    tabela = tabela.reset_index(drop=True)
    tabela.index = tabela.index + 1
    st.dataframe(
        tabela, width='stretch', height=560,
        column_config={T("col_kills"): st.column_config.NumberColumn(format="%d")},
    )
    # export button (a useful portfolio bonus)
    st.download_button(
        T("download_csv"),
        tabela.to_csv(index=False).encode("utf-8"),
        file_name=f"drg_kills_snapshot_{snap_id}.csv", mime="text/csv",
    )

conn.close()
