import os
import re
import unicodedata
from datetime import datetime, time

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st


# ------------------------------------------------------------
# Etiquetas legibles para segmentos horarios (1..12)
# Cada segmento representa una banda de 2 horas.
# ------------------------------------------------------------
SEG_LABELS = {
    1:  "Seg 1 (00–02 hs)",
    2:  "Seg 2 (02–04 hs)",
    3:  "Seg 3 (04–06 hs)",
    4:  "Seg 4 (06–08 hs)",
    5:  "Seg 5 (08–10 hs)",
    6:  "Seg 6 (10–12 hs)",
    7:  "Seg 7 (12–14 hs)",
    8:  "Seg 8 (14–16 hs)",
    9:  "Seg 9 (16–18 hs)",
    10: "Seg 10 (18–20 hs)",
    11: "Seg 11 (20–22 hs)",
    12: "Seg 12 (22–24 hs)",
}


def strip_accents(s: str) -> str:
    """
    Quita tildes/acentos de un texto.
    Ej: 'miércoles' -> 'miercoles'
    Útil para normalizar textos y ordenar categorías.
    """
    s = str(s)
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def seg_label(seg) -> str:
    """
    Devuelve la etiqueta bonita del segmento.
    Si llega algo raro (NaN, None), devuelve texto seguro.
    """
    try:
        s = int(seg)
        return SEG_LABELS.get(s, f"Seg {s}")
    except Exception:
        return "Seg N/A"


# -------------------------------------------------------------------
# CONFIGURACIÓN GENERAL DE LA APP (título, ícono, layout)
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Repartidor | Rappi Stats",
    page_icon="📦",
    layout="wide"
)


# -------------------------------------------------------------------
# FUNCIONES AUXILIARES (helpers)
# -------------------------------------------------------------------
def parse_hora_ampm(x: str):
    """
    Convierte textos tipo:
      '6:39 a. m.'   '10:12 p. m.'   '6:39 am'  '10:12 pm'
    a un objeto datetime.time (hora/minutos).

    ¿Por qué?
    - Para graficar por hora, necesitamos un formato consistente.
    - Las capturas/Excel pueden venir con formatos variados (a. m., p. m., etc.).
    """
    if pd.isna(x):
        return pd.NaT

    # Normalizamos texto: minúsculas, sin espacios raros
    s = str(x).strip().lower()

    # Reemplazamos variantes típicas del español a formato am/pm estándar
    s = (s
         .replace("a. m.", "am")
         .replace("p. m.", "pm")
         .replace("a.m.", "am")
         .replace("p.m.", "pm"))

    # Colapsamos múltiples espacios a uno solo
    s = re.sub(r"\s+", " ", s).strip()

    # Intentamos parsear con el formato: hora 12h : minutos + am/pm
    try:
        dt = datetime.strptime(s, "%I:%M %p")  # %I: 1-12, %p: AM/PM
        return dt.time()
    except Exception:
        return pd.NaT


def to_num(series: pd.Series) -> pd.Series:
    """Convierte una serie a numérica (float), poniendo NaN si no se puede."""
    return pd.to_numeric(series, errors="coerce")


def _resolve_fallback_path(path_fallback: str) -> str:
    """
    En local suele ser 'Pedidos_Maestro.xlsx'.
    En cloud suele ser 'data/Pedidos_Maestro.xlsx'.
    Esta función intenta varias rutas para evitar FileNotFoundError.
    """
    candidates = [
        path_fallback,
        "data/Pedidos_Maestro.xlsx",
        "Pedidos_Maestro.xlsx",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    # Si ninguna existe, devolvemos la original (así el error es explícito)
    return path_fallback


@st.cache_data(show_spinner=False)
def load_data(uploaded_file=None, path_fallback="data/Pedidos_Maestro.xlsx") -> pd.DataFrame:
    """
    Carga el Excel y hace una "limpieza mínima" para que el dashboard funcione.

    cache_data:
    - Streamlit memoriza el resultado mientras el archivo no cambie.
    - Hace la app más rápida y fluida.
    """
    # 1) Carga del archivo
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)
    else:
        resolved = _resolve_fallback_path(path_fallback)
        df = pd.read_excel(resolved)

    # 2) Renombramos columnas para tener nombres coherentes (normalización)
    #    Esto evita romper el dashboard si el excel tiene variantes.
    rename_map = {
        "Seg Horario": "Segmento horario",
        "Hora de pedido": "Hora",
        "Tipo de Establecimiento": "Tipo de establecimiento",
        "RAPPI RECOMPENSA": "RappiRecompensa",
        "TARIFA": "Tarifa",
        "PROPINA": "Propina",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # ------------------------------------------------------------
    # Compatibilidad con excels donde el "nombre del comercio"
    # viene en "Tipo de Establecimiento" (aunque el nombre confunda).
    #
    # Objetivo:
    # - Que el dashboard siempre tenga una columna "Establecimiento"
    # ------------------------------------------------------------
    if "Establecimiento" not in df.columns:
        # Caso 1: luego del rename, quedó como "Tipo de establecimiento"
        if "Tipo de establecimiento" in df.columns:
            df["Establecimiento"] = df["Tipo de establecimiento"]

        # Caso 2: por si no se renombró (excel distinto)
        elif "Tipo de Establecimiento" in df.columns:
            df["Establecimiento"] = df["Tipo de Establecimiento"]


    # -------------------------------------------------------------------
    # 3) Normalización robusta de Fecha (maneja mezcla de formatos)
    # - dayfirst=True (formato típico AR)
    # - si existen DIA y MES y no coincide, corregimos usando DIA/MES como verdad
    # -------------------------------------------------------------------
    if "Fecha" in df.columns:
        # Parseo inicial: evita invertir 1/10/2025 -> 10/1/2025
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)

        # Corrección usando DIA y MES como referencia (si están disponibles y confiables)
        if ("DIA" in df.columns) and ("MES" in df.columns):
            df["DIA"] = pd.to_numeric(df["DIA"], errors="coerce")
            df["MES"] = pd.to_numeric(df["MES"], errors="coerce")

            dia_from_fecha = df["Fecha"].dt.day
            mes_from_fecha = df["Fecha"].dt.month

            mismatch = (
                df["Fecha"].notna() &
                df["DIA"].notna() & df["MES"].notna() &
                ((dia_from_fecha != df["DIA"]) | (mes_from_fecha != df["MES"]))
            )

            if mismatch.any():
                # Tomamos el año desde Fecha ya parseada (si hubiera NaN, quedará NaN y no reconstruye)
                year_from_fecha = df["Fecha"].dt.year

                df.loc[mismatch, "Fecha"] = pd.to_datetime(
                    dict(
                        year=year_from_fecha[mismatch],
                        month=df.loc[mismatch, "MES"],
                        day=df.loc[mismatch, "DIA"],
                    ),
                    errors="coerce"
                )

        # Columna Mes (YYYY-MM), útil para análisis mensual
        df["Mes"] = df["Fecha"].dt.to_period("M").astype(str)

        # Día de semana en español, ordenado (para gráficos/heatmap)
        df["DiaSemana_num"] = df["Fecha"].dt.dayofweek
        dias_es = {
            0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
            4: "Viernes", 5: "Sábado", 6: "Domingo"
        }
        df["DiaSemana"] = df["DiaSemana_num"].map(dias_es)
        orden_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        df["DiaSemana"] = pd.Categorical(df["DiaSemana"], categories=orden_dias, ordered=True)

    # 4) Hora: la convertimos a time + variables derivadas (hora decimal y hora entera)
    if "Hora" in df.columns:
        df["Hora_time"] = df["Hora"].apply(parse_hora_ampm)

        # Hora_decimal: útil para análisis (ej 18.5 = 18:30)
        df["Hora_decimal"] = df["Hora_time"].apply(
            lambda t: (t.hour + t.minute / 60) if isinstance(t, time) else np.nan
        )

        # Hora_hh: solo la hora (0..23), útil para histograma y agrupación
        df["Hora_hh"] = df["Hora_time"].apply(
            lambda t: t.hour if isinstance(t, time) else np.nan
        )

    # 5) Campos numéricos: aseguramos tipo numérico para sumar/promediar
    numeric_cols = ["Monto", "Tarifa", "RappiRecompensa", "Propina", "EFECTIVO", "MONTO EFECTIVO"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = to_num(df[c])

    # 6) Segmento horario a entero (1..12)
    if "Segmento horario" in df.columns:
        df["Segmento horario"] = pd.to_numeric(df["Segmento horario"], errors="coerce").astype("Int64")

    # 7) Flag de doblete + Pedidos_contados (normal=1, doblete=2)
    if "Doblete" in df.columns:
        df["EsDoblete"] = df["Doblete"].notna() & (df["Doblete"].astype(str).str.strip() != "")
        df["Pedidos_contados"] = df["Doblete"].apply(lambda x: 2 if pd.notna(x) else 1)
    else:
        df["EsDoblete"] = False
        df["Pedidos_contados"] = 1

    return df


# -------------------------------------------------------------------
# UI: Encabezado principal del Dashboard
# -------------------------------------------------------------------
st.title("📊 Dashboard para Repartidores — Control & Optimización")
st.caption(
    "Objetivo: detectar *cuándo conviene conectarse*, "
    "*qué segmentos rinden más* y *qué comercios aparecen con frecuencia*."
)

# -------------------------------------------------------------------
# Sidebar: carga de datos + filtros
# -------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Datos")
    uploaded = st.file_uploader("Subí tu Excel (opcional)", type=["xlsx"])
    st.divider()
    st.header("🎛️ Filtros")

# Cargamos datos (si el usuario no sube archivo, usamos el fallback)
df = load_data(uploaded_file=uploaded, path_fallback="data/Pedidos_Maestro.xlsx")

if df.empty:
    st.warning("No hay datos para mostrar.")
    st.stop()

# -------------------------------------------------------------------
# FILTROS (se aplican sobre una copia df -> dff)
# -------------------------------------------------------------------
dff = df.copy()

with st.sidebar:
    # Filtro de fechas (si existe la columna Fecha)
    if "Fecha" in dff.columns and dff["Fecha"].notna().any():
        min_date = dff["Fecha"].min().date()
        max_date = dff["Fecha"].max().date()

        date_range = st.date_input(
            "Rango de fechas",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )
    else:
        date_range = None
        st.info("No se detectó columna Fecha para filtrar.")

    # Filtro por segmento horario
    if "Segmento horario" in dff.columns:
        segs = sorted([int(x) for x in dff["Segmento horario"].dropna().unique()])
        seg_sel = st.multiselect("Segmento horario", options=segs, default=segs)
    else:
        seg_sel = []

    # Filtro por establecimiento
    if "Establecimiento" in dff.columns:
        estabs = sorted(dff["Establecimiento"].dropna().unique())
        estab_sel = st.multiselect("Establecimiento", options=estabs, default=[])
    else:
        estab_sel = []

    # Filtro doblete
    is_doblete = st.selectbox("Doblete", ["Todos", "Solo dobletes", "Sin dobletes"])

# Aplicación de filtros
if date_range and "Fecha" in dff.columns:
    d0, d1 = date_range
    dff = dff[dff["Fecha"].dt.date.between(d0, d1, inclusive="both")]

if "Segmento horario" in dff.columns and seg_sel:
    dff = dff[dff["Segmento horario"].isin(seg_sel)]

if "Establecimiento" in dff.columns and estab_sel:
    dff = dff[dff["Establecimiento"].isin(estab_sel)]

if "EsDoblete" in dff.columns:
    if is_doblete == "Solo dobletes":
        dff = dff[dff["EsDoblete"]]
    elif is_doblete == "Sin dobletes":
        dff = dff[~dff["EsDoblete"]]

# -------------------------------------------------------------------
# Panel de control (debug didáctico)
# Muestra el DataFrame resultante DESPUÉS de aplicar filtros
# -------------------------------------------------------------------
st.caption("🔎 El siguiente panel muestra los datos exactos usados para los cálculos.")

with st.expander("🧪 Panel de control — ver DataFrame filtrado (dff)"):
    # 1) Resumen rápido
    c1, c2, c3 = st.columns(3)
    c1.metric("Filas (registros)", f"{len(dff):,}".replace(",", "."))
    c2.metric("Columnas", str(dff.shape[1]))
    c3.metric("Pedidos (según DF)", str(len(dff)))

    # (extra útil) rango real de Fecha en el DF filtrado
    if "Fecha" in dff.columns and dff["Fecha"].notna().any():
        st.write("**Rango real de Fecha (dff):**", dff["Fecha"].min(), "→", dff["Fecha"].max())

    # 2) Mostrar nombres de columnas (sirve para diagnosticar)
    st.write("**Columnas disponibles:**")
    st.code(", ".join(list(dff.columns)))

    # 3) Control de cuántas filas mostrar (para no colgar la app)
    max_rows = st.slider("Filas a mostrar", min_value=10, max_value=500, value=50, step=10)

    # 4) Mostramos una muestra del DataFrame (las primeras N filas)
    st.dataframe(dff.head(max_rows), use_container_width=True)


# -------------------------------------------------------------------
# Horas trabajadas (aprox) — cálculo correcto por día
# Lógica:
# - Para cada día:
#     * contamos segmentos horarios distintos
#     * cada segmento equivale a 2 horas
# - Sumamos las horas de todos los días del período analizado
# -------------------------------------------------------------------
if ("Fecha" in dff.columns) and ("Segmento horario" in dff.columns) and dff["Fecha"].notna().any():
    segmentos_por_dia = dff.groupby(dff["Fecha"].dt.date)["Segmento horario"].nunique()
    horas_trabajadas_aprox = int((segmentos_por_dia * 2).sum())
else:
    horas_trabajadas_aprox = 0


# -------------------------------------------------------------------
# KPIs (tarjetas)
# -------------------------------------------------------------------
colA, colB, colC, colD, colE, colF = st.columns(6)

total_pedidos = int(dff["Pedidos_contados"].sum()) if "Pedidos_contados" in dff.columns else len(dff)

total_monto = float(dff["Monto"].sum()) if "Monto" in dff.columns else 0.0
avg_monto = float(dff["Monto"].mean()) if "Monto" in dff.columns else 0.0
total_propina = float(dff["Propina"].sum()) if "Propina" in dff.columns else 0.0
total_recomp = float(dff["RappiRecompensa"].sum()) if "RappiRecompensa" in dff.columns else 0.0

propina_pct = (total_propina / total_monto * 100) if total_monto > 0 else 0.0
recomp_pct = (total_recomp / total_monto * 100) if total_monto > 0 else 0.0

colA.metric("Pedidos", f"{total_pedidos:,}".replace(",", "."))
colB.metric("Monto total", f"${total_monto:,.0f}".replace(",", "."))
colC.metric("Ticket promedio", f"${avg_monto:,.0f}".replace(",", "."))
colD.metric("Propina total", f"${total_propina:,.0f}".replace(",", "."), f"{propina_pct:.1f}%")
colE.metric("Recompensas", f"${total_recomp:,.0f}".replace(",", "."), f"{recomp_pct:.1f}%")
colF.metric("Horas trabajadas (≈)", f"{horas_trabajadas_aprox} h")


# -------------------------------------------------------------------
# GRÁFICOS (versión mobile-friendly con Altair)
# -------------------------------------------------------------------
left, right = st.columns([1.2, 1.0])

with left:
    st.subheader("📅 Pedidos por día de la semana")

    if "DiaSemana" in dff.columns and "Pedidos_contados" in dff.columns:
        pedidos_dia = (
            dff.groupby("DiaSemana")["Pedidos_contados"]
            .sum()
            .reset_index(name="Pedidos")
        )

        chart_dia = (
            alt.Chart(pedidos_dia)
            .mark_bar()
            .encode(
                x=alt.X("DiaSemana:N", title="Día", sort=None),
                y=alt.Y("Pedidos:Q", title="Pedidos (contando dobletes)"),
                tooltip=[
                    alt.Tooltip("DiaSemana:N", title="Día"),
                    alt.Tooltip("Pedidos:Q", title="Pedidos"),
                ],
            )
            .properties(height=300)
            .configure_view(strokeWidth=0)
        )

        st.altair_chart(chart_dia, use_container_width=True)

    else:
        st.info("Faltan columnas (DiaSemana y/o Pedidos_contados).")

with right:
    st.subheader("🕒 Pedidos por segmento horario (contando dobletes)")

    if "Segmento horario" in dff.columns and "Pedidos_contados" in dff.columns:
        seg = (
            dff.groupby("Segmento horario")["Pedidos_contados"]
            .sum()
            .reindex(range(1, 13), fill_value=0)
            .reset_index(name="Pedidos")
        )

        seg["Segmento_label"] = seg["Segmento horario"].apply(seg_label)
        ordered_labels = [SEG_LABELS[i] for i in range(1, 13)]

        chart_seg = (
            alt.Chart(seg)
            .mark_bar()
            .encode(
                x=alt.X(
                    "Segmento_label:N",
                    sort=ordered_labels,
                    title="Segmento horario (franjas de 2 horas)",
                ),
                y=alt.Y("Pedidos:Q", title="Pedidos (contando dobletes)"),
                tooltip=[
                    alt.Tooltip("Segmento_label:N", title="Segmento"),
                    alt.Tooltip("Pedidos:Q", title="Pedidos"),
                ],
            )
            .properties(height=300)
            .configure_view(strokeWidth=0)
        )

        st.altair_chart(chart_seg, use_container_width=True)

    else:
        st.info("Faltan columnas (Segmento horario y/o Pedidos_contados).")


# -------------------------------------------------------------------
# Ingreso promedio (ponderado por pedidos_contados)
# -------------------------------------------------------------------
left2, right2 = st.columns([1.2, 1.0])

with left2:
    st.subheader("💵 Ingreso promedio por pedido según día (con dobletes)")

    if "DiaSemana" in dff.columns and "Monto" in dff.columns and "Pedidos_contados" in dff.columns:
        # Promedio ponderado: total monto / total pedidos equivalentes
        ingreso_prom_por_dia = (
            dff.groupby("DiaSemana")
            .apply(lambda g: g["Monto"].sum() / g["Pedidos_contados"].sum()
                   if g["Pedidos_contados"].sum() > 0 else 0.0)
            .reset_index(name="Monto_promedio")
        )

        chart_ing_dia = (
            alt.Chart(ingreso_prom_por_dia)
            .mark_bar()
            .encode(
                x=alt.X("DiaSemana:N", title="Día", sort=None),
                y=alt.Y("Monto_promedio:Q", title="Ingreso promedio ($/pedido)"),
                tooltip=[
                    alt.Tooltip("DiaSemana:N", title="Día"),
                    alt.Tooltip("Monto_promedio:Q", title="Ingreso promedio", format=",.0f"),
                ],
            )
            .properties(height=300)
            .configure_view(strokeWidth=0)
        )

        st.altair_chart(chart_ing_dia, use_container_width=True)

    else:
        st.info("Faltan columnas (DiaSemana, Monto, Pedidos_contados).")

with right2:
    st.subheader("💵 Ingreso promedio por pedido según segmento horario (con dobletes)")

    if "Segmento horario" in dff.columns and "Monto" in dff.columns and "Pedidos_contados" in dff.columns:
        ingreso_prom_por_seg = (
            dff.groupby("Segmento horario")
            .apply(lambda g: g["Monto"].sum() / g["Pedidos_contados"].sum()
                   if g["Pedidos_contados"].sum() > 0 else 0.0)
            .reindex(range(1, 13), fill_value=0.0)
            .reset_index(name="Monto_promedio")
        )

        ingreso_prom_por_seg["Segmento_label"] = ingreso_prom_por_seg["Segmento horario"].apply(seg_label)
        ordered_labels = [SEG_LABELS[i] for i in range(1, 13)]

        chart_ing_seg = (
            alt.Chart(ingreso_prom_por_seg)
            .mark_bar()
            .encode(
                x=alt.X("Segmento_label:N", sort=ordered_labels, title="Segmento horario"),
                y=alt.Y("Monto_promedio:Q", title="Ingreso promedio ($/pedido)"),
                tooltip=[
                    alt.Tooltip("Segmento_label:N", title="Segmento"),
                    alt.Tooltip("Monto_promedio:Q", title="Ingreso promedio", format=",.0f"),
                ],
            )
            .properties(height=300)
            .configure_view(strokeWidth=0)
        )

        st.altair_chart(chart_ing_seg, use_container_width=True)

    else:
        st.info("Faltan columnas (Segmento horario, Monto, Pedidos_contados).")


st.divider()

# -------------------------------------------------------------------
# Top comercios
# -------------------------------------------------------------------
c1, c2 = st.columns([1.0, 1.0])

with c1:
    st.subheader("🏪 Top comercios por cantidad")
    if "Establecimiento" in dff.columns:
        top_n = (
            dff.groupby("Establecimiento")
            .size()
            .reset_index(name="Pedidos")
            .sort_values("Pedidos", ascending=False)
            .head(12)
        )
        st.dataframe(top_n, use_container_width=True, hide_index=True)
    else:
        st.info("No se encontró Establecimiento.")

with c2:
    st.subheader("💰 Top comercios por monto")
    if "Establecimiento" in dff.columns and "Monto" in dff.columns:
        top_m = (
            dff.groupby("Establecimiento")["Monto"]
            .sum()
            .reset_index()
            .sort_values("Monto", ascending=False)
            .head(12)
        )
        st.dataframe(top_m, use_container_width=True, hide_index=True)
    else:
        st.info("No se encontró Establecimiento y/o Monto.")

st.divider()

# -------------------------------------------------------------------
# Heatmap — Día de semana vs Segmento (cantidad de pedidos)
# - Conteo visible + "color" por intensidad con ProgressColumn (sin Styler)
# - Columnas etiquetadas con franja horaria
# -------------------------------------------------------------------
st.subheader("🔥 Heatmap — Día de semana vs Segmento (cantidad de pedidos)")

if ("DiaSemana" in dff.columns) and ("Segmento horario" in dff.columns):
    heat = pd.pivot_table(
        dff,
        index="DiaSemana",
        columns="Segmento horario",
        aggfunc="size",
        fill_value=0
    )

    heat = heat.rename(columns=lambda c: seg_label(c))
    ordered_cols = [SEG_LABELS[i] for i in range(1, 13)]
    heat = heat.reindex(columns=ordered_cols).fillna(0).astype(int)

    max_val = int(heat.to_numpy().max()) if heat.size else 0
    if max_val == 0:
        max_val = 1

    column_config = {}
    for col in heat.columns:
        column_config[col] = st.column_config.ProgressColumn(
            label=col,
            help="Cantidad de pedidos en este día/segmento",
            format="%d",
            min_value=0,
            max_value=max_val
        )

    st.dataframe(
        heat,
        use_container_width=True,
        column_config=column_config
    )
else:
    st.info("Faltan columnas para el heatmap (DiaSemana y Segmento horario).")

st.divider()

# -------------------------------------------------------------------
# Monto ganado por mes (Altair, ordenado cronológicamente)
# -------------------------------------------------------------------
st.subheader("📈 Monto ganado por mes")

if ("Fecha" in dff.columns) and ("Monto" in dff.columns) and dff["Fecha"].notna().any():
    dfm = dff.dropna(subset=["Fecha", "Monto"]).copy()

    # Fecha "inicio de mes" para ordenar
    dfm["Mes_inicio"] = dfm["Fecha"].dt.to_period("M").dt.to_timestamp()

    monto_mes = (
        dfm.groupby("Mes_inicio")["Monto"]
        .sum()
        .reset_index()
        .sort_values("Mes_inicio")
    )

    # Etiqueta en español "Octubre 2025"
    meses_es = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    monto_mes["Mes_label"] = (
        monto_mes["Mes_inicio"].dt.month.map(meses_es)
        + " "
        + monto_mes["Mes_inicio"].dt.year.astype(str)
    )

    ordered_month_labels = monto_mes["Mes_label"].tolist()

    chart_mes = (
        alt.Chart(monto_mes)
        .mark_bar()
        .encode(
            x=alt.X("Mes_label:N", sort=ordered_month_labels, title="Mes"),
            y=alt.Y("Monto:Q", title="Monto ganado ($)"),
            tooltip=[
                alt.Tooltip("Mes_label:N", title="Mes"),
                alt.Tooltip("Monto:Q", title="Monto", format=",.0f"),
            ],
        )
        .properties(height=320)
        .configure_view(strokeWidth=0)
    )

    st.altair_chart(chart_mes, use_container_width=True)
else:
    st.info("Faltan columnas (Fecha y/o Monto) para generar la gráfica mensual.")
