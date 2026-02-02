import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import re
from datetime import datetime, time
import unicodedata


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


def seg_label(seg):
    """
    Devuelve la etiqueta bonita del segmento.
    Si llega algo raro (NaN, None), devuelve texto seguro.
    """
    try:
        s = int(seg)
        return SEG_LABELS.get(s, f"Seg {s}")
    except:
        return "Seg N/A"


# -------------------------------------------------------------------
# CONFIGURACIÓN GENERAL DE LA APP (título, ícono, layout)
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard Repartidor | Rappi Stats",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# -------------------------------------------------------------------
# Estilos: mejora de lectura en celular (colapsa columnas en pantallas angostas)
# -------------------------------------------------------------------
st.markdown(
    """
    <style>
    @media (max-width: 768px) {
      div[data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
      }
      section[data-testid="stSidebar"] {
        width: 100% !important;
      }
    }
    </style>
    """,
    unsafe_allow_html=True,
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
    - Porque para graficar por hora, necesitamos un formato consistente.
    - Las capturas vienen con formatos variados (a. m., p. m., etc.).
    """
    if pd.isna(x):
        return pd.NaT  # "Not a Time": equivalente a un valor faltante

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
    except:
        return pd.NaT


def to_num(series):
    """
    Convierte una serie a numérica (float), poniendo NaN si no se puede.
    Útil porque en Excel a veces hay celdas vacías o texto mezclado.
    """
    return pd.to_numeric(series, errors="coerce")


@st.cache_data(show_spinner=False)
def load_data(uploaded_file=None, path_fallback="data/Pedidos_Maestro.xlsx"):
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
        df = pd.read_excel(path_fallback)

    # 2) Renombramos columnas para tener nombres coherentes (normalización)
    #    Esto evita romper el dashboard si el excel tiene variantes.
    rename_map = {
        "Seg Horario": "Segmento horario",
        "Hora de pedido": "Hora",
        "Tipo de Establecimiento": "Establecimiento",
        "Tipo de pedido": "Tipo de pedido",
        "RAPPI RECOMPENSA": "RappiRecompensa",
        "TARIFA": "Tarifa",
        "PROPINA": "Propina",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # -------------------------------------------------------------------
    # Normalización robusta de Fecha (maneja mezcla de formatos)
    # - Primero intentamos parsear con dayfirst=True (formato típico AR)
    # - Luego, si existen DIA y MES (y están bien), corregimos las filas ambiguas
    # -------------------------------------------------------------------
    if "Fecha" in df.columns:
        # 1) Parseo inicial: dayfirst=True evita invertir 1/10/2025 -> 10/1/2025
        df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)

        # 2) Corrección usando DIA y MES como referencia (si están disponibles)
        if ("DIA" in df.columns) and ("MES" in df.columns):
            # Aseguramos numéricos
            df["DIA"] = pd.to_numeric(df["DIA"], errors="coerce")
            df["MES"] = pd.to_numeric(df["MES"], errors="coerce")

            # Extraemos día/mes desde la Fecha parseada
            dia_from_fecha = df["Fecha"].dt.day
            mes_from_fecha = df["Fecha"].dt.month

            # Detectamos filas donde Fecha NO coincide con DIA/MES del Excel
            mismatch = (
                df["Fecha"].notna() &
                df["DIA"].notna() & df["MES"].notna() &
                ((dia_from_fecha != df["DIA"]) | (mes_from_fecha != df["MES"]))
            )

            # Si hay mismatch, reconstruimos Fecha con año de la Fecha + DIA/MES del Excel
            # (asumimos que el año ya está bien o al menos es recuperable)
            if mismatch.any():
                # Tomamos año desde Fecha; si falta, intentamos tomarlo desde el texto original
                year_from_fecha = df["Fecha"].dt.year

                # Reconstrucción segura: YYYY-M-D
                df.loc[mismatch, "Fecha"] = pd.to_datetime(
                    dict(
                        year=year_from_fecha[mismatch],
                        month=df.loc[mismatch, "MES"],
                        day=df.loc[mismatch, "DIA"],
                    ),
                    errors="coerce"
                )


        # 3) Fecha a formato datetime (permite filtrar por rango y agrupar por día)
        if "Fecha" in df.columns:
            df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")

        # Extra: columna Mes para análisis mensual (YYYY-MM)
        if "Fecha" in df.columns:
            # to_period("M") genera periodo mensual; luego lo pasamos a string 'YYYY-MM'
            df["Mes"] = df["Fecha"].dt.to_period("M").astype(str)

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

        # 6) Día de semana (derivado de Fecha): permite heatmap Día vs Segmento
        # 6) Día de semana (derivado de Fecha): lo forzamos a español y orden lógico
        if "Fecha" in df.columns:
            # 0=Lunes ... 6=Domingo (esto es estándar en pandas)
            df["DiaSemana_num"] = df["Fecha"].dt.dayofweek

            # Mapeo fijo a español (no depende del locale del sistema)
            dias_es = {
                0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
                4: "Viernes", 5: "Sábado", 6: "Domingo"
            }
            df["DiaSemana"] = df["DiaSemana_num"].map(dias_es)

        # Categórico ordenado: importante para que gráficos/heatmap salgan en orden
        orden_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        df["DiaSemana"] = pd.Categorical(df["DiaSemana"], categories=orden_dias, ordered=True)


        # 7) Segmento horario a entero (1..12)
        if "Segmento horario" in df.columns:
            df["Segmento horario"] = pd.to_numeric(df["Segmento horario"], errors="coerce").astype("Int64")

        # 8) Flag de doblete: útil para filtrar y mostrar impacto de dobletes
        if "Doblete" in df.columns:
            df["EsDoblete"] = df["Doblete"].notna() & (df["Doblete"].astype(str).str.strip() != "")
        else:
            df["EsDoblete"] = False

        # Pedidos_contados: normal=1, doblete=2 (misma lógica que tu notebook)
        if "Doblete" in df.columns:
            df["Pedidos_contados"] = df["Doblete"].apply(lambda x: 2 if pd.notna(x) else 1)
        else:
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
    dff = dff[(dff["Fecha"].dt.date >= d0) & (dff["Fecha"].dt.date <= d1)]

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

    # 2) Mostrar nombres de columnas (sirve para diagnosticar)
    st.write("**Columnas disponibles:**")
    st.code(", ".join(list(dff.columns)))

    # 3) Control de cuántas filas mostrar (para no colgar la app)
    max_rows = st.slider("Filas a mostrar", min_value=10, max_value=500, value=50, step=10)

    # 4) Mostramos una muestra del DataFrame (las primeras N filas)
    st.dataframe(dff.head(max_rows), use_container_width=True)

# Nota:
# Las horas trabajadas son una estimación.
# No mide conexión real, sino presencia en segmentos horarios.
# Es útil para comparar períodos y eficiencia (ingresos / hora).

# -------------------------------------------------------------------
# Horas trabajadas (aprox) — cálculo correcto por día
# Lógica:
# - Para cada día:
#     * contamos segmentos horarios distintos
#     * cada segmento equivale a 2 horas
# - Sumamos las horas de todos los días del período analizado
# -------------------------------------------------------------------

if ("Fecha" in dff.columns) and ("Segmento horario" in dff.columns):

    # Cantidad de segmentos horarios distintos POR DÍA
    segmentos_por_dia = (
        dff
        .groupby(dff["Fecha"].dt.date)["Segmento horario"]
        .nunique()
    )

    # Cada segmento equivale a 2 horas → convertimos a horas
    horas_trabajadas_aprox = int((segmentos_por_dia * 2).sum())

else:
    horas_trabajadas_aprox = 0






# -------------------------------------------------------------------
# KPIs (tarjetas principales)
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# KPIs (tarjetas)
# -------------------------------------------------------------------
colA, colB, colC, colD, colE, colF = st.columns(6)

total_pedidos = int(dff["Pedidos_contados"].sum()) if "Pedidos_contados" in dff.columns else len(dff)


# Totales numéricos (si no existen columnas, usamos 0)
total_monto = float(dff["Monto"].sum()) if "Monto" in dff.columns else 0.0
avg_monto = float(dff["Monto"].mean()) if "Monto" in dff.columns else 0.0
total_propina = float(dff["Propina"].sum()) if "Propina" in dff.columns else 0.0
total_recomp = float(dff["RappiRecompensa"].sum()) if "RappiRecompensa" in dff.columns else 0.0

# Evitamos dividir por cero
propina_pct = (total_propina / total_monto * 100) if total_monto > 0 else 0.0
recomp_pct = (total_recomp / total_monto * 100) if total_monto > 0 else 0.0

# .metric permite: label, value, delta (lo usamos para el %)
colA.metric("Pedidos", f"{total_pedidos:,}".replace(",", "."))
colB.metric("Monto total", f"${total_monto:,.0f}".replace(",", "."))
colC.metric("Ticket promedio", f"${avg_monto:,.0f}".replace(",", "."))

# Mostramos $ como valor + % como delta (queda visual y ejecutivo)
colD.metric("Propina total", f"${total_propina:,.0f}".replace(",", "."), f"{propina_pct:.1f}%")
colE.metric("Recompensas", f"${total_recomp:,.0f}".replace(",", "."), f"{recomp_pct:.1f}%")

colF.metric("Horas trabajadas (≈)", f"{horas_trabajadas_aprox} h")

# -------------------------------------------------------------------
# GRÁFICOS
# -------------------------------------------------------------------


left, right = st.columns([1.2, 1.0])

with left:
    st.subheader("📅 Pedidos por día de la semana")

    if "DIA TEXTO" in dff.columns and "Pedidos_contados" in dff.columns:

        # Normalizar día
        dff["_dia_norm"] = (
            dff["DIA TEXTO"].astype(str).str.strip().str.lower().apply(strip_accents)
        )

        orden = ["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]

        pedidos = (
            dff.groupby("_dia_norm")["Pedidos_contados"].sum().reset_index()
        )

        pedidos["_dia_norm"] = pd.Categorical(pedidos["_dia_norm"], categories=orden, ordered=True)
        pedidos = pedidos.sort_values("_dia_norm")

        st.bar_chart(pedidos.set_index("_dia_norm")["Pedidos_contados"])

    else:
        st.info("Falta DIA TEXTO y/o Pedidos_contados.")

#st.write("Filas (size):", int(len(dff)))
#st.write("Doblettes (sum EsDoblete):", int(dff["EsDoblete"].astype(int).sum()) if "EsDoblete" in dff.columns else "No existe")
#st.write("Pedidos equivalentes:", int((1 + dff["EsDoblete"].astype(int)).sum()) if "EsDoblete" in dff.columns else int(len(dff)))







with right:
    st.subheader("🕒 Pedidos por segmento horario (contando dobletes)")

    if "Segmento horario" in dff.columns and "Pedidos_contados" in dff.columns:
        # 1) Sumamos pedidos equivalentes por segmento (normal=1, doblete=2)
        seg = (
            dff.groupby("Segmento horario")["Pedidos_contados"]
            .sum()
            .reindex(range(1, 13), fill_value=0)  # asegura segmentos 1..12 aunque falten
            .reset_index(name="Pedidos")
        )

        # 2) Creamos etiqueta legible para el eje X
        seg["Segmento_label"] = seg["Segmento horario"].apply(seg_label)

        # 3) Orden definitivo de etiquetas (Seg 1 ... Seg 12)
        ordered_labels = [SEG_LABELS[i] for i in range(1, 13)]

        # 4) Convertimos a Categorical con orden explícito
        seg["Segmento_label"] = pd.Categorical(
            seg["Segmento_label"],
            categories=ordered_labels,
            ordered=True
        )

        # 5) Ordenamos el DataFrame por esa columna categórica
        seg = seg.sort_values("Segmento_label")

        # 6) Graficamos
        st.bar_chart(seg.set_index("Segmento_label")["Pedidos"])

    else:
        st.info("Faltan columnas (Segmento horario y/o Pedidos_contados).")

#************************************************************************************************************************

left, right = st.columns([1.2, 1.0])


with left:

    #Ingreso promedio por pedido según día (con dobletes)
    st.subheader("💵 Ingreso promedio por pedido según día (con dobletes)")

    if "DIA TEXTO" in dff.columns and "Monto" in dff.columns and "Pedidos_contados" in dff.columns:

        # 1) Normalizamos día (igual que en Pedidos por día)
        dff["_dia_norm"] = (
            dff["DIA TEXTO"].astype(str).str.strip().str.lower().apply(strip_accents)
        )

        # 2) Orden fijo (sin tildes)
        orden = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

        # 3) Calculamos promedio real por pedido (ponderado por Pedidos_contados)
        ingreso_prom_por_dia = (
            dff.groupby("_dia_norm")
            .apply(lambda g: g["Monto"].sum() / g["Pedidos_contados"].sum()
                    if g["Pedidos_contados"].sum() > 0 else 0)
            .reset_index(name="Monto_promedio")
        )

        # 4) Forzamos orden categórico y ordenamos
        ingreso_prom_por_dia["_dia_norm"] = pd.Categorical(
            ingreso_prom_por_dia["_dia_norm"],
            categories=orden,
            ordered=True
        )
        ingreso_prom_por_dia = ingreso_prom_por_dia.sort_values("_dia_norm")

        # 5) Graficamos
        st.bar_chart(ingreso_prom_por_dia.set_index("_dia_norm")["Monto_promedio"])

    else:
        st.info("Faltan columnas (DIA TEXTO, Monto, Pedidos_contados).")


with right:
    #Ingreso promedio por pedido según segmento horario (con dobletes)

    st.subheader("💵 Ingreso promedio por pedido según segmento horario (con dobletes)")

    if "Segmento horario" in dff.columns and "Monto" in dff.columns and "Pedidos_contados" in dff.columns:

        ingreso_prom_por_seg = (
            dff.groupby("Segmento horario")
            .apply(lambda g: g["Monto"].sum() / g["Pedidos_contados"].sum() if g["Pedidos_contados"].sum() > 0 else 0)
            .reindex(range(1, 13), fill_value=0)
            .reset_index(name="Monto_promedio")
        )

        ingreso_prom_por_seg["Segmento_label"] = ingreso_prom_por_seg["Segmento horario"].apply(seg_label)

        ordered_labels = [SEG_LABELS[i] for i in range(1, 13)]
        ingreso_prom_por_seg["Segmento_label"] = pd.Categorical(
            ingreso_prom_por_seg["Segmento_label"],
            categories=ordered_labels,
            ordered=True
        )
        ingreso_prom_por_seg = ingreso_prom_por_seg.sort_values("Segmento_label")

        st.bar_chart(ingreso_prom_por_seg.set_index("Segmento_label")["Monto_promedio"])

    else:
        st.info("Faltan columnas (Segmento horario, Monto, Pedidos_contados).")


#***********************************************************************************************************************

st.divider()

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
# - Mantenemos el conteo en cada celda (número visible)
# - Sumamos "color" usando ProgressColumn (sin pandas Styler, evita errores)
# - Mostramos columnas con etiqueta: "Seg X (hh–hh hs)" y en orden 1..12
# -------------------------------------------------------------------
st.subheader("🔥 Heatmap — Día de semana vs Segmento (cantidad de pedidos)")

if ("DiaSemana" in dff.columns) and ("Segmento horario" in dff.columns):
    # 1) Construimos la tabla dinámica:
    #    filas = día de semana, columnas = segmento horario
    #    valor = cantidad de pedidos (conteo de filas)
    heat = pd.pivot_table(
        dff,
        index="DiaSemana",
        columns="Segmento horario",
        aggfunc="size",     # size = contar registros (pedidos)
        fill_value=0
    )

    # 2) Renombramos columnas (1..12) a etiquetas amigables:
    #    ej: 7 -> "Seg 7 (12–14 hs)"
    #    Nota: seg_label() y SEG_LABELS deben estar definidos arriba en tu script.
    heat = heat.rename(columns=lambda c: seg_label(c))

    # 3) Aseguramos el orden correcto de columnas (Seg 1 ... Seg 12)
    #    Si falta algún segmento en los datos, igual lo dejamos (queda NaN),
    #    por eso rellenamos con 0 al final.
    ordered_cols = [SEG_LABELS[i] for i in range(1, 13)]
    heat = heat.reindex(columns=ordered_cols).fillna(0).astype(int)

    # 4) Escala global del "color": tomamos el máximo de toda la tabla
    max_val = int(heat.to_numpy().max()) if heat.size else 0
    if max_val == 0:
        max_val = 1  # evita que la barra tenga escala 0 cuando todo es cero

    # 5) Configuramos cada columna como ProgressColumn:
    #    - Se ve como un "mapa de calor" (intensidad)
    #    - Mantiene el número visible dentro de cada celda
    column_config = {}
    for col in heat.columns:
        column_config[col] = st.column_config.ProgressColumn(
            label=col,  # ya incluye "Seg X (hh–hh hs)"
            help="Cantidad de pedidos en este día/segmento",
            format="%d",
            min_value=0,
            max_value=max_val
        )

    # 6) Mostramos el heatmap
    st.dataframe(
        heat,
        use_container_width=True,
        column_config=column_config
    )

else:
    st.info("Faltan columnas para el heatmap (DiaSemana y Segmento horario).")



st.divider()


st.subheader("📈 Monto ganado por mes")

# Verificamos que existan las columnas necesarias
if "MES TEXTO" in dff.columns and "Monto" in dff.columns:
    
    # --- 1. LIMPIEZA DE DATOS ---
    # Creamos una copia para no afectar el dataframe original
    df_plot = dff.copy()
    
    # Convertimos Fecha a datetime (si no lo es) para poder ordenar
    if "Fecha" in df_plot.columns:
        df_plot["Fecha"] = pd.to_datetime(df_plot["Fecha"], errors='coerce')
    
    # Eliminamos filas donde el Mes o el Monto sean nulos (el origen del "nan 2025")
    df_plot = df_plot.dropna(subset=["MES TEXTO", "Monto"])
    
    # Filtramos casos donde el texto sea literalmente "nan" o esté vacío
    df_plot = df_plot[df_plot["MES TEXTO"].astype(str).str.lower() != "nan"]
    df_plot["_mes_texto"] = df_plot["MES TEXTO"].astype(str).str.strip()

    # --- 2. AGRUPACIÓN ---
    # Sumamos los montos por mes
    monto_mes = (
        df_plot.groupby("_mes_texto")["Monto"]
        .sum()
        .reset_index()
    )

    # --- 3. LÓGICA DE ORDENAMIENTO ---
    if "Fecha" in df_plot.columns:
        # Obtenemos la fecha mínima de cada mes para saber su posición en el tiempo
        # Usamos inner join para descartar meses que no tengan ninguna fecha válida
        ref = (
            df_plot.dropna(subset=["Fecha"])
            .groupby("_mes_texto")["Fecha"]
            .min()
            .reset_index()
        )
        
        # Creamos la llave de ordenamiento YYYY-MM (ej: 2025-01)
        ref["_mes_key"] = ref["Fecha"].dt.strftime('%Y-%m')
        ref["_anio"] = ref["Fecha"].dt.year

        monto_mes = monto_mes.merge(ref, on="_mes_texto", how="inner")

        # Creamos la etiqueta final: "Enero 2026"
        monto_mes["_mes_label"] = (
            monto_mes["_mes_texto"] + " " + 
            monto_mes["_anio"].astype(int).astype(str)
        )

        # Ordenamos el DataFrame físicamente por la fecha real
        monto_mes = monto_mes.sort_values("_mes_key")
    else:
        monto_mes["_mes_label"] = monto_mes["_mes_texto"]

    # --- 4. VISUALIZACIÓN CON PLOTLY ---
    if not monto_mes.empty:
        fig = px.bar(
            monto_mes, 
            x="_mes_label", 
            y="Monto",
            text_auto='.2s', # Muestra etiquetas como 520k, 45k, etc.
            labels={"_mes_label": "Mes", "Monto": "Monto Ganado ($)"},
            template="plotly_white"
        )

        # Ajustes estéticos y forzar el orden del eje X según el DataFrame
        fig.update_traces(marker_color='#0068c9') # Color azul similar al original
        fig.update_layout(
            xaxis={'categoryorder':'array', 'categoryarray': monto_mes['_mes_label']},
            margin=dict(l=20, r=20, t=20, b=20)
        )
        
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("No hay datos válidos para mostrar después de filtrar valores nulos.")

else:
    st.info("Falta MES TEXTO y/o Monto en el archivo para generar la gráfica.")



