import os
from pathlib import Path

import pandas as pd
import streamlit as st

from data.database import (
    init_db,
    archivo_ya_procesado,
    registrar_archivo_procesado,
    insertar_en_db,
    fetch_all,
    update_rows,
    mark_rows_as_kame,
    reset_db,
)
from data.extractor_internacional import leer_cartola_internacional
from dashboard import show_dashboard


TIPO_GASTO_OPTIONS = [
    "movilizacion",
    "comida",
    "alojamiento",
    "combustible",
    "electronic",
    "libro",
    "otro",
    "Airbnb",
    "Uber",
    "Google Suite",
    "Hubspot",
    "Canva",
    "Shutterstock",
    "Google Ads",
    "Facebook Ads",
]


# =========================
# Password protection
# =========================
def require_password():
    if "APP_PASSWORD" not in st.secrets:
        st.error("APP_PASSWORD no está configurado en secrets.")
        st.stop()

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Acceso protegido")

        password = st.text_input(
            "Ingrese la contraseña",
            type="password",
        )

        if password and password == st.secrets["APP_PASSWORD"]:
            st.session_state.authenticated = True
            st.rerun()
        elif password:
            st.error("Contraseña incorrecta")

        st.stop()


# =========================
# Utilities
# =========================
def _get_base_path() -> str:
    candidates = ["/mount/src/vs_bci_internacional", "/mount", "."]
    for c in candidates:
        try:
            Path(c).mkdir(parents=True, exist_ok=True)
            test = Path(c) / ".write_test"
            test.write_text("ok", encoding="utf-8")
            test.unlink(missing_ok=True)
            return c
        except Exception:
            continue
    return "."


# =========================
# Main app
# =========================
def main():
    st.set_page_config(page_title="BCI Internacional", layout="wide")

    # 🔐 Password gate
    require_password()

    st.title("BCI – Estado de Cuenta Internacional (USD)")

    base_path = _get_base_path()
    db_path = str(Path(base_path) / "cartolas_bci_internacional.db")
    conn = init_db(db_path)

    # -------------------------
    # 1) Upload PDFs
    # -------------------------
    st.subheader("1) Cargar PDFs (Internacional)")
    uploaded = st.file_uploader("Sube uno o más PDF", type=[
                                "pdf"], accept_multiple_files=True)

    exclude_terms_raw = st.text_input(
        "Excluir términos en DESCRIPCION (separados por coma)",
        value="",
        help="Ej: PAGO, TOTAL, ABONO",
    )
    exclude_terms = [t.strip().lower()
                     for t in exclude_terms_raw.split(",") if t.strip()]

    if uploaded:
        ingested = 0
        skipped = 0

        for f in uploaded:
            filename = f.name

            if archivo_ya_procesado(conn, filename):
                skipped += 1
                continue

            pdf_bytes = f.read()

            try:
                rows = leer_cartola_internacional(pdf_bytes, filename=filename)
            except Exception as e:
                st.error(f"Error leyendo {filename}: {e}")
                continue

            if exclude_terms:
                rows = [
                    r for r in rows
                    if not any(term in (r.get("DESCRIPCION", "").lower()) for term in exclude_terms)
                ]

            if rows:
                insertar_en_db(conn, rows)
                registrar_archivo_procesado(conn, filename)
                ingested += 1
            else:
                st.warning(
                    f"No se extrajeron filas desde {filename}. No se marca como procesado.")
                skipped += 1

        st.success(f"Listo. Ingestados: {ingested} | Omitidos: {skipped}")
        st.rerun()

    # -------------------------
    # Load DB
    # -------------------------
    cols, rows = fetch_all(conn)
    df_db = pd.DataFrame(rows, columns=cols)

    # -------------------------
    # Dashboard
    # -------------------------
    st.divider()
    show_dashboard(df_db)

    # -------------------------
    # 2) Conciliación / Kame
    # -------------------------
    st.divider()
    st.subheader("2) Conciliación / Kame")

    if df_db.empty:
        st.info("No hay transacciones aún.")
        return

    pending = df_db[df_db["FACT_KAME"] == 0].copy()
    done = df_db[df_db["FACT_KAME"] == 1].copy()

    st.markdown("### Pendientes (no ingresadas en Kame)")

    if pending.empty:
        st.success("No hay pendientes 🎉")
    else:
        pending = pending.sort_values(["FECHA_OPERACION", "MONTO_TOTAL"], ascending=[
                                      True, False]).reset_index(drop=True)
        pending["_FACT_KAME_DB"] = pending["FACT_KAME"]
        pending["FACT_KAME"] = False

        editable_cols = [
            "_RID_",
            "TITULAR_NOMBRE",
            "FECHA_OPERACION",
            "DESCRIPCION",
            "CIUDAD",
            "PAIS",
            "MONTO_TOTAL",
            "TIPO_GASTO",
            "CONCILIADO",
            "FACT_KAME",
        ]

        show_all = st.checkbox(
            "Mostrar todas las filas pendientes", value=False)
        view_df = pending[editable_cols].head(20 if not show_all else None)

        edited = st.data_editor(
            view_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "_RID_": st.column_config.NumberColumn("ID", disabled=True),
                "TITULAR_NOMBRE": st.column_config.TextColumn("Titular", disabled=True),
                "FECHA_OPERACION": st.column_config.TextColumn("Fecha (MM/DD/YY)", disabled=True),
                "DESCRIPCION": st.column_config.TextColumn("Descripción", disabled=True),
                "CIUDAD": st.column_config.TextColumn("Ciudad", disabled=True),
                "PAIS": st.column_config.TextColumn("País", disabled=True),
                "MONTO_TOTAL": st.column_config.NumberColumn("Monto (US$)", format="%.2f", disabled=True),
                "TIPO_GASTO": st.column_config.SelectboxColumn(
                    "Tipo gasto",
                    options=TIPO_GASTO_OPTIONS,
                ),
                "CONCILIADO": st.column_config.CheckboxColumn("Conciliado"),
                "FACT_KAME": st.column_config.CheckboxColumn("Mover a Kame"),
            },
        )

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Guardar cambios"):
                update_rows(
                    conn, edited[["_RID_", "TIPO_GASTO", "CONCILIADO"]].to_dict("records"))
                st.success("Cambios guardados")
                st.rerun()

        with col2:
            selected = edited[edited["FACT_KAME"] == True]
            valid = (
                not selected.empty
                and selected["CONCILIADO"].all()
                and not selected["TIPO_GASTO"].fillna("").str.strip().eq("").any()
            )

            if st.button("Mover a Kame", disabled=not valid):
                update_rows(
                    conn, edited[["_RID_", "TIPO_GASTO", "CONCILIADO"]].to_dict("records"))
                mark_rows_as_kame(conn, selected["_RID_"].tolist())
                st.success(f"{len(selected)} movidas a Kame")
                st.rerun()

    # -------------------------
    # Export
    # -------------------------
    st.divider()
    st.subheader("3) Exportar")

    st.download_button(
        "Descargar CSV",
        df_db.to_csv(index=False).encode("utf-8"),
        file_name="transacciones_internacional.csv",
    )


if __name__ == "__main__":
    main()
