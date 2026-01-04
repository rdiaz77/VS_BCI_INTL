from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber
from unidecode import unidecode


DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{2}\b")
PAIS_RE = re.compile(r"^[A-Z]{2}$")
REF_RE = re.compile(r"^\d{10,}$")

# Examples: 49,44 ; -17,35 ; 49.640,00
AMOUNT_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d{2})$|^-?\d+(?:,\d{2})$")


def _norm(s: str) -> str:
    """Uppercase + remove accents (robust PDF matching)."""
    return unidecode(s).upper()


def _to_float(amount_str: str) -> float:
    s = amount_str.strip().replace("US$", "").replace("$", "")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def _ddmmyy_to_mmddyy(ddmmyy: str) -> str:
    dd, mm, yy = ddmmyy.split("/")
    return f"{mm}/{dd}/{yy}"


# =========================
# Header extraction
# =========================
def _extract_header_fields(full_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns:
      titular_full_name, titular_first_name, fecha_estado
    """
    titular_full = None
    titular_first = None
    fecha_estado = None

    # Full name
    m = re.search(
        r"NOMBRE DEL TITULAR\s+([A-ZÁÉÍÓÚÑ ]+)\s+N° DE TARJETA",
        full_text,
        re.DOTALL,
    )
    if m:
        titular_full = " ".join(m.group(1).split()).strip()
        titular_first = titular_full.split()[0]

    # Statement date (not critical, but used for archivo_origen)
    m2 = re.search(r"FECHA ESTADO DE CUENTA\s+(\d{2}/\d{2}/\d{4})", full_text)
    if m2:
        fecha_estado = m2.group(1)

    return titular_full, titular_first, fecha_estado


def _build_archivo_origen(
    filename: str,
    titular_full: Optional[str],
    fecha_estado: Optional[str],
) -> str:
    if titular_full and fecha_estado:
        safe_name = "_".join(titular_full.split())
        safe_date = fecha_estado.replace("/", "-")
        return f"BCI_INT_{safe_name}_{safe_date}"
    return filename


def _find_trailing_amounts(tokens: List[str]) -> List[str]:
    trailing = []
    for t in reversed(tokens):
        if AMOUNT_RE.match(t):
            trailing.append(t)
        else:
            if trailing:
                break
    return list(reversed(trailing))


def _split_desc_city_pais(tokens_after_date: List[str], pais: str) -> Tuple[str, str]:
    if not pais:
        return (" ".join(tokens_after_date).strip(), "")

    try:
        idx = len(tokens_after_date) - 1 - list(reversed(tokens_after_date)).index(pais)
    except ValueError:
        return (" ".join(tokens_after_date).strip(), "")

    before_pais = tokens_after_date[:idx]
    if not before_pais:
        return ("", "")

    if len(before_pais) <= 1:
        return (" ".join(before_pais).strip(), "")

    city_tokens = before_pais[-3:] if len(before_pais) > 3 else before_pais[-1:]
    desc_tokens = before_pais[:-len(city_tokens)] if len(before_pais) > len(city_tokens) else []

    desc = " ".join(desc_tokens).strip()
    city = " ".join(city_tokens).strip()

    if not desc:
        desc = " ".join(before_pais).strip()
        city = ""

    return desc, city


def _parse_transaction_line(
    line: str,
    archivo_origen: str,
    titular_first_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    tokens = line.split()

    try:
        date_idx = next(i for i, t in enumerate(tokens) if DATE_RE.fullmatch(t))
    except StopIteration:
        return None

    trailing = _find_trailing_amounts(tokens)
    if not trailing:
        return None

    monto_origen = trailing[-2] if len(trailing) >= 2 else None
    monto_usd = trailing[-1]

    desc_tokens = tokens[date_idx + 1 : len(tokens) - len(trailing)]

    pais = ""
    ciudad = ""
    if desc_tokens and PAIS_RE.match(desc_tokens[-1]):
        pais = desc_tokens[-1]
        desc, ciudad = _split_desc_city_pais(desc_tokens, pais)
    else:
        desc = " ".join(desc_tokens).strip()

    if not desc or desc.upper().startswith("TOTAL"):
        return None

    ref = ""
    if date_idx >= 2 and REF_RE.match(tokens[date_idx - 1]):
        ref = tokens[date_idx - 1]

    try:
        monto_usd_f = _to_float(monto_usd)
        monto_origen_f = _to_float(monto_origen) if monto_origen else None
    except Exception:
        return None

    fecha_mmddyy = _ddmmyy_to_mmddyy(tokens[date_idx])

    return {
        "TITULAR_NOMBRE": titular_first_name,  # ✅ NEW COLUMN
        "FECHA_OPERACION": fecha_mmddyy,
        "DESCRIPCION": desc,
        "CIUDAD": ciudad,
        "PAIS": pais,
        "REF_INTERNACIONAL": ref,
        "MONTO_ORIGEN": monto_origen_f,
        "MONTO_OPERACION": monto_usd_f,
        "MONTO_TOTAL": monto_usd_f,
        "ARCHIVO_ORIGEN": archivo_origen,
        "TIPO_GASTO": "",
        "FACT_KAME": 0,
        "CONCILIADO": 0,
    }


def leer_cartola_internacional(pdf_bytes: bytes, filename: str = "archivo.pdf") -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page_texts = [(p.extract_text() or "") for p in pdf.pages]
        full_text = "\n".join(page_texts)

        titular_full, titular_first, fecha_estado = _extract_header_fields(full_text)
        archivo_origen = _build_archivo_origen(filename, titular_full, fecha_estado)

        in_transacciones = False
        in_comisiones = False

        for t in page_texts:
            for raw_line in t.splitlines():
                line = " ".join(raw_line.split())
                if not line:
                    continue

                u = _norm(line)

                if "2. INFORMACION DE TRANSACCIONES" in u:
                    in_transacciones = True
                    in_comisiones = False
                    continue

                if "COMISIONES, OTROS CARGOS Y ABONOS" in u:
                    in_comisiones = True
                    in_transacciones = False
                    continue

                if u.startswith("TOTAL TARJETA"):
                    in_transacciones = False
                    continue

                if u.startswith(
                    (
                        "NUMERO",
                        "FECHA",
                        "DESCRIPCION",
                        "CIUDAD",
                        "PAIS",
                        "MONTO",
                        "TOTAL DE PAGOS",
                        "TOTAL DE COMPRAS",
                    )
                ):
                    continue

                if not (in_transacciones or in_comisiones):
                    continue

                if not DATE_RE.search(line):
                    continue

                row = _parse_transaction_line(
                    line,
                    archivo_origen,
                    titular_first_name=titular_first,
                )
                if row:
                    rows.append(row)

    # Deduplicate
    uniq = {}
    for r in rows:
        key = (
            r["TITULAR_NOMBRE"],
            r["FECHA_OPERACION"],
            r["DESCRIPCION"],
            r.get("PAIS", ""),
            r["MONTO_OPERACION"],
            r["ARCHIVO_ORIGEN"],
        )
        uniq[key] = r

    return list(uniq.values())
# ---end--- 
