#!/usr/bin/env python3
"""
dashboard.py — o PAINEL do DRG Stats Tracker.

Lê o banco drg_stats.db (as "fotos" que o snapshot.py foi gravando) e desenha
tudo bonito num site interativo: ranking de kills por espécie, evolução ao longo
do tempo, créditos, tempo de jogo e o "quanto você matou desde a última foto".

Feito pra quem NÃO é dev: tem um botão "📸 Atualizar agora" que lê o save e grava
uma foto nova sem precisar de terminal. Basta abrir e clicar.

Como abrir (o jeito fácil):
    -> dê DUPLO CLIQUE em "Abrir Dashboard.bat"

Como abrir (o jeito manual):
    pip install streamlit
    streamlit run dashboard.py

Depende de: streamlit (que já traz junto o pandas e o altair que usamos aqui),
mais os arquivos do projeto: drg_stats.db, drg_save_parser.py, snapshot.py.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import pandas as pd
import altair as alt
import streamlit as st

# snapshot.py é do mesmo projeto: reaproveitamos a lógica de achar o save e gravar
# a foto, pra o botão "Atualizar agora" funcionar sem o usuário abrir um terminal.
import snapshot
import drg_save_parser as drg   # pra ler overclocks/cosméticos direto do save atual

# ----------------------------------------------------------------------------
# PALETA (tema DRG: preto industrial + laranja âmbar).
# A regra de dataviz aqui: kills por espécie é MAGNITUDE -> uma cor só, do claro
# ao escuro (ramp sequencial). Nada de arco-íris. O laranja combina com o jogo.
# ----------------------------------------------------------------------------
DB_PATH = "drg_stats.db"

COR_FUNDO      = "#12100e"   # preto quente (rocha)
COR_SURFACE    = "#1c1917"   # cartões
COR_TEXTO      = "#f5efe6"   # texto principal (creme)
COR_TEXTO_FRACO = "#a89f92"  # eixos/labels
COR_LARANJA    = "#eb6834"   # âmbar DRG (destaque)
COR_LARANJA_ESC = "#8f3a18"  # ponta escura do ramp
COR_GRID       = "#332e29"   # linhas de grade discretas

# Ramp sequencial de 1 cor (claro -> escuro) para as barras de magnitude.
RAMP_LARANJA = ["#f6b98f", "#f19a63", "#eb6834", "#c14f22", "#8f3a18"]


# ----------------------------------------------------------------------------
# ACESSO AO BANCO
# ----------------------------------------------------------------------------
def conectar() -> sqlite3.Connection | None:
    """Abre o banco em modo só-leitura (o painel nunca escreve direto)."""
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def carregar_snapshots(conn) -> pd.DataFrame:
    """Todas as fotos, mais antiga -> mais nova. Vira uma tabela do pandas."""
    df = pd.read_sql_query(
        "SELECT * FROM snapshots ORDER BY id ASC", conn,
    )
    if not df.empty:
        # taken_at vem como texto ISO em UTC (é assim que a gente grava — padrão
        # certo, independente de fuso). Pra EXIBIR, convertemos pro fuso LOCAL do
        # PC (ex.: Brasil = UTC-3) e só então tiramos o timezone (deixa "ingênua"
        # pro Altair/strftime). datetime.now().astimezone().tzinfo pega o fuso do
        # PC automaticamente — sem hardcode, funciona em qualquer máquina.
        fuso_local = datetime.now().astimezone().tzinfo
        df["quando"] = (pd.to_datetime(df["taken_at"], utc=True)
                        .dt.tz_convert(fuso_local)
                        .dt.tz_localize(None))
    return df


def carregar_kills(conn, snapshot_id: int) -> pd.DataFrame:
    """As contagens por espécie de UMA foto específica, do maior pro menor."""
    df = pd.read_sql_query(
        """SELECT guid, name, count
           FROM kills WHERE snapshot_id = ?
           ORDER BY count DESC""",
        conn, params=(snapshot_id,),
    )
    # nome pode ser NULL (bicho sem tradução). Mostramos o começo do GUID no lugar.
    df["especie"] = df["name"].fillna("GUID:" + df["guid"].str.slice(0, 8))
    return df


def carregar_deltas(conn, id_atual: int, id_anterior: int) -> pd.DataFrame:
    """
    Quanto cada espécie CRESCEU entre duas fotos. Repare: o delta é CALCULADO
    na hora com um JOIN — a gente guarda fatos (contagens), não derivados.
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
# FORMATADORES (deixar número gigante legível)
# ----------------------------------------------------------------------------
def fmt_num(n) -> str:
    """75466 -> '75.466' (ponto de milhar no estilo BR)."""
    if n is None:
        return "—"
    return f"{int(n):,}".replace(",", ".")


def fmt_horas(segundos) -> str:
    if not segundos:
        return "—"
    h = segundos / 3600
    return f"{h:,.1f} h".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_quando(dt) -> str:
    """Data/hora amigável."""
    if pd.isna(dt):
        return "—"
    return dt.strftime("%d/%m/%Y %H:%M")


# ----------------------------------------------------------------------------
# AÇÃO: tirar uma foto nova (o que o snapshot.py faz, só que por um botão)
# ----------------------------------------------------------------------------
def atualizar_agora() -> str:
    """Lê o save e grava uma foto nova. Devolve uma mensagem pro usuário."""
    save_path = snapshot.find_save()
    if save_path is None or not save_path.exists():
        return "❌ Não achei o save automaticamente. Rode o snapshot.py apontando o caminho uma vez."
    names = snapshot.load_names()
    conn = snapshot.conectar(DB_PATH)
    try:
        snap_id = snapshot.tirar_snapshot(conn, save_path, names)
    finally:
        conn.close()
    if snap_id is None:
        return "ℹ️ Nada mudou desde a última foto — nenhuma nova gravada."
    return f"✅ Foto nova gravada (snapshot #{snap_id})! Rock and Stone! 🪨"


# ----------------------------------------------------------------------------
# GRÁFICOS (Altair)
# ----------------------------------------------------------------------------
def grafico_barras_especies(df: pd.DataFrame, top_n: int) -> alt.Chart:
    """Ranking de kills por espécie — barras horizontais, ramp laranja (magnitude)."""
    d = df.head(top_n).copy()
    base = alt.Chart(d).encode(
        y=alt.Y("especie:N", sort="-x", title=None,
                axis=alt.Axis(labelColor=COR_TEXTO, labelLimit=220,
                              labelFontSize=12, domainColor=COR_GRID, ticks=False)),
        x=alt.X("count:Q", title="Kills",
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, titleColor=COR_TEXTO_FRACO,
                              gridColor=COR_GRID, format="~s")),
    )
    barras = base.mark_bar(cornerRadiusEnd=4, height=alt.RelativeBandSize(0.72)).encode(
        # cor = magnitude (ramp sequencial de 1 hue), sem legenda: a barra fala por si.
        color=alt.Color("count:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None),
        tooltip=[alt.Tooltip("especie:N", title="Espécie"),
                 alt.Tooltip("count:Q", title="Kills", format=",")],
    )
    # rótulo do valor direto na ponta da barra (leitura sem passar o mouse)
    rotulos = base.mark_text(
        align="left", dx=4, color=COR_TEXTO, fontSize=11,
    ).encode(text=alt.Text("count:Q", format=","))

    altura = max(120, len(d) * 26)
    return (barras + rotulos).properties(height=altura).configure_view(
        strokeWidth=0
    ).configure(background=COR_SURFACE)


def grafico_evolucao(df: pd.DataFrame, coluna: str, titulo: str, cor: str) -> alt.Chart:
    """Evolução de uma métrica ao longo das fotos — linha única no tempo."""
    d = df.dropna(subset=[coluna])
    linha = alt.Chart(d).mark_line(
        color=cor, strokeWidth=2, point=alt.OverlayMarkDef(color=cor, size=55),
    ).encode(
        x=alt.X("quando:T", title=None,
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, gridColor=COR_GRID)),
        y=alt.Y(f"{coluna}:Q", title=titulo,
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, titleColor=COR_TEXTO_FRACO,
                              gridColor=COR_GRID, format="~s")),
        tooltip=[alt.Tooltip("quando:T", title="Quando", format="%d/%m/%Y %H:%M"),
                 alt.Tooltip(f"{coluna}:Q", title=titulo, format=",")],
    ).properties(height=260).configure_view(strokeWidth=0).configure(background=COR_SURFACE)
    return linha


# ----------------------------------------------------------------------------
# OVERCLOCKS / COSMÉTICOS (lê o SAVE atual + cruza com guids.json)
# ----------------------------------------------------------------------------
# Diferente do resto do painel (que lê o BANCO/histórico), o comparativo de
# overclocks é sobre o estado ATUAL. Então lemos o save direto. Cacheado com
# @st.cache_data pra não reparsear o save a cada clique (o Streamlit re-roda o
# script inteiro toda interação — ver seção 11.0 do CLAUDE.md).
@st.cache_data(show_spinner=False)
def carregar_guids() -> dict | None:
    """A tabela de referência (GUID -> arma/nome). É o 'Y' do comparativo."""
    p = Path("guids.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@st.cache_data(show_spinner=False)
def estado_do_save() -> dict | None:
    """O que você TEM: overclocks forjados + cosméticos, lidos do save atual."""
    save = snapshot.find_save()
    if save is None or not Path(save).exists():
        return None
    s = drg.parse_save(str(save), enemy_names=snapshot.load_names())
    return {"forjados": {g.upper() for g in s["forged_schematics"]},
            "vanity":   {g.upper() for g in s["vanity_items"]}}


def tabela_overclocks(ref: dict, forjados: set) -> pd.DataFrame:
    """Por arma: quantos overclocks você tem, o total, e a lista do que falta."""
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
        "faltando": ", ".join(sorted(faltam[a])) or "— completo!",
    } for a in total]
    return pd.DataFrame(linhas).sort_values(["pct", "arma"])


def grafico_overclocks(df: pd.DataFrame) -> alt.Chart:
    """Barra de progresso por arma: fundo = total, laranja = quantos você tem."""
    altura = max(160, len(df) * 28)
    base = alt.Chart(df).encode(
        y=alt.Y("arma:N", sort=alt.EncodingSortField("pct", order="ascending"),
                title=None, axis=alt.Axis(labelColor=COR_TEXTO_FRACO)),
    )
    fundo = base.mark_bar(color=COR_GRID, cornerRadiusEnd=3,
                          height=alt.RelativeBandSize(0.68)).encode(
        x=alt.X("total:Q", title="Overclocks",
                axis=alt.Axis(labelColor=COR_TEXTO_FRACO, tickMinStep=1)),
    )
    frente = base.mark_bar(cornerRadiusEnd=3, height=alt.RelativeBandSize(0.68)).encode(
        x=alt.X("tem:Q"),
        color=alt.Color("pct:Q", scale=alt.Scale(range=RAMP_LARANJA), legend=None),
        tooltip=[alt.Tooltip("arma:N", title="Arma"),
                 alt.Tooltip("classe:N", title="Classe"),
                 alt.Tooltip("rotulo:N", title="Tem / Total"),
                 alt.Tooltip("faltando:N", title="Faltando")],
    )
    rotulo = base.mark_text(align="left", dx=5, color=COR_TEXTO).encode(
        x=alt.X("total:Q"), text="rotulo:N",
    )
    return ((fundo + frente + rotulo).properties(height=altura)
            .configure_view(strokeWidth=0)
            .configure_axis(grid=False, domainColor=COR_GRID)
            .configure(background=COR_SURFACE))


# ============================================================================
# APLICAÇÃO
# ============================================================================
st.set_page_config(page_title="DRG Stats Tracker", page_icon="🪨", layout="wide")

# --- um tema escuro estilo caverna via CSS (Streamlit deixa injetar) ---
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
st.caption("Suas estatísticas de Deep Rock Galactic — extraídas do save, com histórico. "
           "Rock and Stone!")

conn = conectar()

# --- Caso 1: banco ainda não existe / está vazio ---------------------------
if conn is None or carregar_snapshots(conn).empty:
    st.warning("Ainda não há nenhuma **foto** no banco. Vamos tirar a primeira?")
    st.write("O botão abaixo lê o save do jogo e grava a primeira foto. "
             "Depois disso os gráficos aparecem sozinhos.")
    if st.button("📸 Tirar a primeira foto", type="primary"):
        with st.spinner("Lendo o save..."):
            msg = atualizar_agora()
        st.info(msg)
        st.rerun()
    st.stop()

snaps = carregar_snapshots(conn)

# --------------------------- BARRA LATERAL ---------------------------------
with st.sidebar:
    st.header("⚙️ Controles")

    if st.button("📸 Atualizar agora", type="primary", width='stretch',
                 help="Lê o save do jogo e grava uma foto nova"):
        with st.spinner("Lendo o save..."):
            msg = atualizar_agora()
        st.session_state["_msg_atualizar"] = msg
        st.rerun()
    if "_msg_atualizar" in st.session_state:
        st.info(st.session_state.pop("_msg_atualizar"))

    st.divider()

    # Escolher qual foto olhar (padrão = a mais recente).
    opcoes = {
        f"#{r.id} — {fmt_quando(r.quando)}": int(r.id)
        for r in snaps.iloc[::-1].itertuples()   # mais nova no topo
    }
    escolha = st.selectbox("Foto (snapshot)", list(opcoes.keys()))
    snap_id = opcoes[escolha]

    top_n = st.slider("Quantas espécies mostrar", 5, 77, 20, step=1)

    st.divider()
    st.caption(f"Fotos no banco: **{len(snaps)}**")
    st.caption(f"Banco: `{Path(DB_PATH).resolve().name}`")

# --------------------------- CABEÇALHO (métricas) --------------------------
linha = snaps[snaps["id"] == snap_id].iloc[0]

# se houver foto anterior, calculamos os "deltas" pra mostrar setinha de variação
anteriores = snaps[snaps["id"] < snap_id]
tem_anterior = not anteriores.empty
linha_ant = anteriores.iloc[-1] if tem_anterior else None

def delta_de(coluna):
    if not tem_anterior or pd.isna(linha[coluna]) or pd.isna(linha_ant[coluna]):
        return None
    d = linha[coluna] - linha_ant[coluna]
    return None if d == 0 else fmt_num(d)

st.subheader(f"📊 Resumo — {fmt_quando(linha['quando'])}")

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("Rank da conta", fmt_num(linha["level"]), delta_de("level"))
c2.metric("Total de kills", fmt_num(linha["total_kills"]), delta_de("total_kills"))
c3.metric("Créditos", fmt_num(linha["credits"]), delta_de("credits"))
c4.metric("Promoções", fmt_num(linha["times_retired"]), delta_de("times_retired"))
# Missões CONCLUÍDAS (o que o jogo mostra, ex.: 445) != Partidas JOGADAS
# (NumberOfGamesPlayed, ex.: 504, inclui abandonadas/falhadas). São stats distintas.
c5.metric("Missões concluídas", fmt_num(linha["missions_completed"]), delta_de("missions_completed"))
c6.metric("Partidas jogadas", fmt_num(linha["games_played"]), delta_de("games_played"))
c7.metric("Tempo de jogo", fmt_horas(linha["playtime_seconds"]))

st.divider()

# --------------------------- ABAS ------------------------------------------
aba_especies, aba_tempo, aba_ocs, aba_desde, aba_tabela = st.tabs(
    ["🐛 Por espécie", "📈 Evolução", "⚙️ Overclocks", "🆕 Desde a última foto", "🗂️ Tabela"]
)

kills = carregar_kills(conn, snap_id)

# ---- Aba 1: ranking por espécie ----
with aba_especies:
    st.markdown(f"**Top {min(top_n, len(kills))} espécies mais mortas** "
                f"(de {len(kills)} no total)")
    st.altair_chart(grafico_barras_especies(kills, top_n), width='stretch')

# ---- Aba 2: evolução no tempo ----
with aba_tempo:
    if len(snaps) < 2:
        st.info("Só existe **uma** foto por enquanto. Tire mais fotos (com o botão "
                "**📸 Atualizar agora**, em dias diferentes) e a evolução aparece aqui. "
                "É o histórico se formando! 📆")
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Total de kills ao longo do tempo**")
            st.altair_chart(grafico_evolucao(snaps, "total_kills", "Kills", COR_LARANJA),
                            width='stretch')
        with col_b:
            st.markdown("**Créditos ao longo do tempo**")
            st.altair_chart(grafico_evolucao(snaps, "credits", "Créditos", "#eda100"),
                            width='stretch')
        col_c, col_d = st.columns(2)
        with col_c:
            st.markdown("**Rank da conta**")
            st.altair_chart(grafico_evolucao(snaps, "level", "Rank", "#1baf7a"),
                            width='stretch')
        with col_d:
            st.markdown("**Tempo de jogo (segundos)**")
            st.altair_chart(grafico_evolucao(snaps, "playtime_seconds", "Segundos", "#e87ba4"),
                            width='stretch')

# ---- Aba 3: overclocks (e cosméticos) ----
with aba_ocs:
    if st.button("🔄 Reler do save", help="Atualiza a leitura de overclocks direto do save"):
        estado_do_save.clear()
        carregar_guids.clear()
        st.rerun()

    ref = carregar_guids()
    estado = estado_do_save()
    if ref is None:
        st.warning("Falta o **guids.json** (a tabela de overclocks/cosméticos) na pasta do projeto.")
    elif estado is None:
        st.warning("Não achei o save do jogo pra ler seus overclocks — ele precisa estar "
                   "acessível **neste PC**. (No PC onde você joga, funciona.)")
    else:
        oc = tabela_overclocks(ref, estado["forjados"])
        tem_t, tot_t = int(oc["tem"].sum()), int(oc["total"].sum())
        m1, m2, m3 = st.columns(3)
        m1.metric("Overclocks forjados", f"{tem_t}/{tot_t}")
        m2.metric("Faltam forjar", fmt_num(tot_t - tem_t))
        m3.metric("Coleção completa", f"{tem_t / tot_t * 100:.0f}%")
        st.progress(tem_t / tot_t)
        st.altair_chart(grafico_overclocks(oc), width='stretch')
        st.caption("Barra cheia = total de overclocks da arma; a parte laranja é quanto "
                   "você já forjou. As armas mais incompletas ficam no topo.")

        with st.expander("📋 O que falta forjar (por arma)"):
            faltantes = (oc[oc["faltam_n"] > 0][["classe", "arma", "rotulo", "faltando"]]
                         .rename(columns={"classe": "Classe", "arma": "Arma",
                                          "rotulo": "Tem/Total", "faltando": "Faltando"}))
            st.dataframe(faltantes.reset_index(drop=True), width='stretch', hide_index=True)

        # --- cosméticos: honesto sobre a incerteza (ver seção 4.2/5 do CLAUDE.md) ---
        st.divider()
        st.markdown("**Cosméticos** — estimativa ⚠️")
        st.caption("O desbloqueio de cosméticos no DRG vem de várias fontes; esta contagem "
                   "pode ficar ABAIXO do real. Trate como estimativa até a gente mapear melhor.")
        possui = estado["vanity"] | estado["forjados"]   # vanity + os forjados de matrix core
        cos = [{"Categoria": cat.replace("Cosmetic - ", ""),
                "Tem": sum(1 for g in ref[cat] if g.upper() in possui), "Total": len(ref[cat])}
               for cat in ["Cosmetic - Headwear", "Cosmetic - Moustache", "Cosmetic - Beard",
                           "Cosmetic - Sideburns", "Victory Moves", "Weapon Skins"] if cat in ref]
        st.dataframe(pd.DataFrame(cos), width='stretch', hide_index=True)

# ---- Aba 4: o que cresceu desde a foto anterior ----
with aba_desde:
    if not tem_anterior:
        st.info("Esta é a foto mais antiga (ou a única). Não há uma anterior pra comparar. "
                "Escolha uma foto mais recente na barra lateral, ou tire fotos novas.")
    else:
        st.markdown(f"**Comparando** a foto #{snap_id} com a #{int(linha_ant['id'])} "
                    f"({fmt_quando(linha_ant['quando'])})")
        deltas = carregar_deltas(conn, snap_id, int(linha_ant["id"]))
        cresceram = deltas[deltas["delta"] > 0]
        if cresceram.empty:
            st.write("Nada mudou entre essas duas fotos. 😴")
        else:
            total_novo = int(cresceram["delta"].sum())
            st.metric("Total de kills novas nesse período", fmt_num(total_novo))
            g = grafico_barras_especies(
                cresceram.rename(columns={"delta": "count"}), min(top_n, len(cresceram))
            )
            st.altair_chart(g, width='stretch')

# ---- Aba 4: tabela crua (com busca) ----
with aba_tabela:
    busca = st.text_input("🔎 Buscar espécie", placeholder="ex.: Grunt, Mactera...")
    tabela = kills[["especie", "count"]].rename(columns={"especie": "Espécie", "count": "Kills"})
    if busca:
        tabela = tabela[tabela["Espécie"].str.contains(busca, case=False, na=False)]
    tabela = tabela.reset_index(drop=True)
    tabela.index = tabela.index + 1
    st.dataframe(
        tabela, width='stretch', height=560,
        column_config={"Kills": st.column_config.NumberColumn(format="%d")},
    )
    # botão pra exportar (bônus útil pra portfólio)
    st.download_button(
        "⬇️ Baixar como CSV",
        tabela.to_csv(index=False).encode("utf-8"),
        file_name=f"drg_kills_snapshot_{snap_id}.csv", mime="text/csv",
    )

conn.close()
