import pandas as pd
import plotly.express as px
import streamlit as st


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["FECHA_DT"] = pd.to_datetime(out["FECHA_OPERACION"], format="%d/%m/%y", errors="coerce")
    return out


def show_dashboard(df_db: pd.DataFrame) -> None:
    st.subheader("Dashboard")

    if df_db.empty:
        st.info("No hay datos aún.")
        return

    df = _parse_dates(df_db)

    # Month filter
    df["MES"] = df["FECHA_DT"].dt.to_period("M").astype(str)
    months = [m for m in sorted(df["MES"].dropna().unique())]
    month_sel = st.selectbox("Filtrar por mes", ["Todos"] + months, index=0)

    if month_sel != "Todos":
        df = df[df["MES"] == month_sel].copy()

    # Text search
    q = st.text_input("Buscar en descripción", value="")
    if q.strip():
        df = df[df["DESCRIPCION"].str.contains(q.strip(), case=False, na=False)]

    # KPIs
    total = df["MONTO_TOTAL"].sum()
    count = len(df)
    avg = df["MONTO_TOTAL"].mean() if count else 0.0
    conc = int((df["CONCILIADO"] == 1).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total (US$)", f"{total:,.2f}")
    c2.metric("Transacciones", f"{count}")
    c3.metric("Promedio (US$)", f"{avg:,.2f}")
    c4.metric("Conciliadas", f"{conc}")

    # Top merchants/descriptions
    top = (
        df.groupby("DESCRIPCION", as_index=False)["MONTO_TOTAL"]
        .sum()
        .sort_values("MONTO_TOTAL", ascending=False)
        .head(10)
    )
    if not top.empty:
        fig = px.bar(top, x="MONTO_TOTAL", y="DESCRIPCION", orientation="h")
        st.plotly_chart(fig, use_container_width=True)

    # Monthly trend
    trend = (
        df.dropna(subset=["FECHA_DT"])
        .groupby(df["FECHA_DT"].dt.to_period("M").astype(str), as_index=False)["MONTO_TOTAL"]
        .sum()
        .rename(columns={"FECHA_DT": "MES"})
    )
    trend.columns = ["MES", "MONTO_TOTAL"]
    if len(trend) > 1:
        fig2 = px.line(trend, x="MES", y="MONTO_TOTAL", markers=True)
        st.plotly_chart(fig2, use_container_width=True)

    # Reconciliation pie
    pie = pd.DataFrame(
        {
            "Estado": ["Conciliadas", "Pendientes"],
            "Cantidad": [int((df["CONCILIADO"] == 1).sum()), int((df["CONCILIADO"] == 0).sum())],
        }
    )
    fig3 = px.pie(pie, names="Estado", values="Cantidad")
    st.plotly_chart(fig3, use_container_width=True)

    with st.expander("Ver tabla filtrada"):
        st.dataframe(
            df[
                [
                    "FECHA_OPERACION",
                    "DESCRIPCION",
                    "CIUDAD",
                    "PAIS",
                    "MONTO_OPERACION",
                    "MONTO_TOTAL",
                    "TIPO_GASTO",
                    "CONCILIADO",
                    "FACT_KAME",
                    "ARCHIVO_ORIGEN",
                ]
            ].sort_values(["FECHA_OPERACION", "MONTO_TOTAL"], ascending=[True, False]),
            use_container_width=True,
        )
