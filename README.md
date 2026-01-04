# BCI International Statements (Streamlit)

International-only Streamlit app to ingest **BCI "Estado de Cuenta Internacional"** PDF statements,
extract transactions, store them in SQLite, reconcile/categorize, mark as "Ingresado en Kame",
and view a dashboard (with **month filter**).

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notes
- Amounts are stored as SQLite `REAL` (numeric) and preserve decimals (USD).
- The app uses `rowid` as a stable identifier for edits.
- If you set `st.secrets["app_password"]`, the app will require it.
