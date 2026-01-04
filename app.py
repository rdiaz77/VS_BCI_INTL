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
    "Google Suite",
    "software",
    "Google Ads",
    "Facebook Ads",
    "Shuttherstock",
    "Canva",
    "Airbnb",
    "Uber",
    "Hubspot",
]


def _get_base_path() -> str:
    """
    Choose a writable base path. Works locally and on some hosted environments.
    """
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


def _require_password():
    """
    Optional password gate: only activates if you set st.secrets["app_password"].
    """
    try:
        expected = st.secrets.get("app_password", None)
    except Exception:
        expected = None

    if not expected:
        return

    pw = st.text_input("Password", type="password")
    if pw != expected:
        st.warning("Password required.")
        st.stop()


def main():
    st.set_page_config(page_title="BCI Internacional", layout="wide")
    _require_password()

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

            # Optional exclude filters
            if exclude_terms:
                filtered = []
                for r in rows:
                    desc = (r.get("DESCRIPCION") or "").lower()
                    if any(term in desc for term in exclude_terms):
                        continue
                    filtered.append(r)
                rows = filtered

            if rows:
                insertar_en_db(conn, rows)
                registrar_archivo_procesado(conn, filename)
                ingested += 1
            else:
                # Don't mark as processed if we extracted nothing
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
    # Dashboard (no graphs)
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
        pending["FACT_KAME"] = False  # UI selection only

        editable_cols = [
            "_RID_",
            "TITULAR_NOMBRE",  # ✅ NEW
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
        view_df = pending[editable_cols].copy()
        if not show_all:
            view_df = view_df.head(20).copy()

        edited = st.data_editor(
            view_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "_RID_": st.column_config.NumberColumn("ID", disabled=True),
                # ✅ NEW
                "TITULAR_NOMBRE": st.column_config.TextColumn("Titular", disabled=True),
                "FECHA_OPERACION": st.column_config.TextColumn("Fecha (MM/DD/YY)", disabled=True),
                "DESCRIPCION": st.column_config.TextColumn("Descripción", disabled=True),
                "CIUDAD": st.column_config.TextColumn("Ciudad", disabled=True),
                "PAIS": st.column_config.TextColumn("País", disabled=True),
                "MONTO_TOTAL": st.column_config.NumberColumn("Monto (US$)", format="%.2f", disabled=True),
                "TIPO_GASTO": st.column_config.SelectboxColumn(
                    "Tipo gasto",
                    options=TIPO_GASTO_OPTIONS,
                    required=False,
                ),
                "CONCILIADO": st.column_config.CheckboxColumn("Conciliado"),
                "FACT_KAME": st.column_config.CheckboxColumn("Mover a Kame"),
            },
        )

        left, right = st.columns([1, 1])

        with left:
            if st.button("Guardar cambios (Tipo gasto / Conciliado)"):
                updates = edited[["_RID_", "TIPO_GASTO", "CONCILIADO"]].to_dict(
                    orient="records")
                update_rows(conn, updates)
                st.success("Guardado.")
                st.rerun()

        with right:
            selected = edited[edited["FACT_KAME"] == True].copy()

            can_move = True
            if selected.empty:
                can_move = False
            else:
                if not selected["CONCILIADO"].all():
                    can_move = False
                if selected["TIPO_GASTO"].fillna("").str.strip().eq("").any():
                    can_move = False

            if st.button("Mover seleccionadas a 'Ingresado en Kame'", disabled=not can_move):
                rowids = selected["_RID_"].astype(int).tolist()

                # Save edits before moving
                updates = edited[["_RID_", "TIPO_GASTO", "CONCILIADO"]].to_dict(
                    orient="records")
                update_rows(conn, updates)

                mark_rows_as_kame(conn, rowids)
                st.success(f"Movidas: {len(rowids)}")
                st.rerun()

            if (not selected.empty) and (not can_move):
                st.info(
                    "Para mover: todas deben estar CONCILIADAS y con TIPO_GASTO definido.")

    st.markdown("### Ingresado en Kame")
    if done.empty:
        st.info("Aún no hay transacciones ingresadas.")
    else:
        st.dataframe(
            done[
                [
                    "TITULAR_NOMBRE",  # ✅ NEW
                    "FECHA_OPERACION",
                    "DESCRIPCION",
                    "CIUDAD",
                    "PAIS",
                    "MONTO_TOTAL",
                    "TIPO_GASTO",
                    "CONCILIADO",
                    "ARCHIVO_ORIGEN",
                ]
            ].sort_values(["FECHA_OPERACION", "MONTO_TOTAL"], ascending=[True, False]),
            use_container_width=True,
            hide_index=True,
        )

    # -------------------------
    # 3) Export / Admin
    # -------------------------
    st.divider()
    st.subheader("3) Exportar / Admin")

    csv = df_db.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar CSV (todas las transacciones)",
        data=csv,
        file_name="transacciones_internacional.csv",
    )

    with st.expander("Reset database (borra todo)"):
        if st.button("RESET DB"):
            reset_db(conn)
            st.warning("DB reseteada.")
            st.rerun()


if __name__ == "__main__":
    main()
# ---end---
