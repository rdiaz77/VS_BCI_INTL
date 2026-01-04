import pandas as pd
import streamlit as st


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["FECHA_DT"] = pd.to_datetime(out["FECHA_OPERACION"], format="%m/%d/%y", errors="coerce")
    return out


def show_dashboard(df_db: pd.DataFrame) -> None:
    st.subheader("Dashboard")

    if df_db is None or df_db.empty:
        st.info("No hay datos aún.")
        return

    df = _parse_dates(df_db)

    # Month filter
    df["MES"] = df["FECHA_DT"].dt.to_period("M").astype(str)
    months = [m for m in sorted(df["MES"].dropna().unique())]
    month_sel = st.selectbox("Filtrar por mes", ["Todos"] + months, index=0)

    if month_sel != "Todos":
        df = df[df["MES"] == month_sel].copy()

    # Search
    q = st.text_input("Buscar en descripción", value="")
    if q.strip():
        df = df[df["DESCRIPCION"].astype(str).str.contains(q.strip(), case=False, na=False)].copy()

    # Numeric safety
    df["MONTO_TOTAL"] = pd.to_numeric(df["MONTO_TOTAL"], errors="coerce").fillna(0.0)
    if "MONTO_OPERACION" in df.columns:
        df["MONTO_OPERACION"] = pd.to_numeric(df["MONTO_OPERACION"], errors="coerce").fillna(0.0)

    # KPIs
    total = float(df["MONTO_TOTAL"].sum())
    count = int(len(df))
    avg = float(df["MONTO_TOTAL"].mean()) if count else 0.0
    conc = int((df.get("CONCILIADO", 0) == 1).sum()) if "CONCILIADO" in df.columns else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total (US$)", f"{total:,.2f}")
    c2.metric("Transacciones", f"{count}")
    c3.metric("Promedio (US$)", f"{avg:,.2f}")
    c4.metric("Conciliadas", f"{conc}")

    with st.expander("Ver tabla filtrada"):
        preferred_cols = [
            "TITULAR_NOMBRE",  # ✅ NEW
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
        cols = [c for c in preferred_cols if c in df.columns]

        df_sorted = df.copy()
        if "FECHA_DT" in df_sorted.columns:
            df_sorted = df_sorted.sort_values(
                ["FECHA_DT", "MONTO_TOTAL"],
                ascending=[True, False],
                na_position="last",
            )
        else:
            df_sorted = df_sorted.sort_values(
                ["FECHA_OPERACION", "MONTO_TOTAL"],
                ascending=[True, False],
                na_position="last",
            )

        st.dataframe(df_sorted[cols], use_container_width=True)
