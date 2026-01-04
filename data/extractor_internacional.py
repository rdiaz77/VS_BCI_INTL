from __future__ import annotations

import re
from typing import BinaryIO, Dict, Any, List, Optional, Tuple
import pdfplumber


DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{2}\b")
PAIS_RE = re.compile(r"^[A-Z]{2}$")
REF_RE = re.compile(r"^\d{10,}$")
PREFIX_RE = re.compile(r"^\d{4}$")
# Amount formats: 49,44 ; -17,35 ; 49.640,00
AMOUNT_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d{2})$|^-?\d+(?:,\d{2})$")


def _to_float(amount_str: str) -> float:
    """
    Convert international statement amount to float.
    Examples: "49,44" -> 49.44 ; "49.640,00" -> 49640.00 ; "-17,35" -> -17.35
    """
    s = amount_str.strip().replace("US$", "").replace("$", "")
    s = s.replace(".", "").replace(",", ".")
    return float(s)


def _extract_header_fields(full_text: str) -> Tuple[Optional[str], Optional[str]]:
    # TITULAR
    titular = None
    m = re.search(r"NOMBRE DEL TITULAR\s+([A-ZÁÉÍÓÚÑ ]+)\s+N° DE TARJETA", full_text, re.DOTALL)
    if m:
        titular = " ".join(m.group(1).split()).strip()

    # FECHA ESTADO DE CUENTA
    fecha_estado = None
    m2 = re.search(r"FECHA ESTADO DE CUENTA\s+(\d{2}/\d{2}/\d{4})", full_text)
    if m2:
        fecha_estado = m2.group(1)

    return titular, fecha_estado


def _build_archivo_origen(filename: str, titular: Optional[str], fecha_estado: Optional[str]) -> str:
    if titular and fecha_estado:
        safe_tit = "_".join(titular.split())
        safe_fecha = fecha_estado.replace("/", "-")
        return f"BCI_INT_{safe_tit}_{safe_fecha}"
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
    """
    Heuristic:
    - City is the last 1-3 tokens immediately before PAIS (if PAIS is present) and not empty.
    - Description is whatever comes before city.
    """
    if not pais:
        return (" ".join(tokens_after_date).strip(), "")

    # tokens_after_date includes city + pais + maybe other text? We will split using last occurrence of pais.
    # Find last index of pais
    try:
        idx = len(tokens_after_date) - 1 - list(reversed(tokens_after_date)).index(pais)
    except ValueError:
        return (" ".join(tokens_after_date).strip(), "")

    before_pais = tokens_after_date[:idx]
    # pick up to last 3 tokens as city
    city_tokens = before_pais[-3:] if before_pais else []
    # but avoid swallowing description if it's short: keep at least 1 token in description when possible
    if len(before_pais) <= 1:
        city_tokens = before_pais
        desc_tokens = []
    else:
        # if before_pais length > 3, treat last 1-3 as city and remaining as description
        desc_tokens = before_pais[:-len(city_tokens)] if city_tokens else before_pais

    city = " ".join(city_tokens).strip()
    desc = " ".join(desc_tokens).strip()

    # if desc ended empty, fallback to all before pais as desc
    if not desc:
        desc = " ".join(before_pais).strip()
        city = ""
    return desc, city


def _parse_transaction_line(line: str, archivo_origen: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single line that includes a date. Returns a normalized row or None.
    Expected formats found in international statements:
      <prefix4> <ref_long> <dd/mm/yy> <desc...> <city...> <PAIS> <monto_origen> <monto_usd>
    Or in commissions block sometimes:
      <prefix4> <ref_long> <dd/mm/yy> <desc...> <city...> <monto_origen> <monto_usd_negative>
      (PAIS may be absent)
    """
    tokens = line.split()
    # Must contain date token
    try:
        date_idx = next(i for i, t in enumerate(tokens) if DATE_RE.fullmatch(t))
    except StopIteration:
        return None

    trailing = _find_trailing_amounts(tokens)
    if not trailing:
        return None

    # Determine monto_origen and monto_usd
    monto_origen = None
    monto_usd = None
    if len(trailing) >= 2:
        monto_origen = trailing[-2]
        monto_usd = trailing[-1]
    else:
        monto_usd = trailing[-1]

    # core tokens before trailing amounts
    core = tokens[: len(tokens) - len(trailing)]

    # detect pais (token right before amounts, in core)
    pais = ""
    if core and PAIS_RE.match(core[-1]):
        pais = core[-1]
        core = core[:-1]

    # detect prefix and ref if present (best-effort)
    prefix = core[0] if len(core) >= 1 and PREFIX_RE.match(core[0]) else ""
    ref = core[1] if len(core) >= 2 and REF_RE.match(core[1]) else ""

    # tokens after date (excluding trailing amounts)
    tokens_after_date = tokens[date_idx + 1 : len(tokens) - len(trailing)]
    # if pais exists and appears inside tokens_after_date at end, keep it there for desc/city split
    desc = ""
    city = ""
    if pais:
        desc, city = _split_desc_city_pais(tokens_after_date, pais)
    else:
        desc = " ".join(tokens_after_date).strip()

    # basic sanity: skip totals
    if not desc or desc.upper().startswith("TOTAL"):
        return None

    # Convert amounts to float
    try:
        monto_usd_f = _to_float(monto_usd)
        monto_origen_f = _to_float(monto_origen) if monto_origen is not None else None
    except Exception:
        return None

    return {
        "FECHA_OPERACION": tokens[date_idx],
        "DESCRIPCION": desc,
        "CIUDAD": city,
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
    """
    Read BCI International statement PDF and return normalized rows for DB insertion.
    """
    rows: List[Dict[str, Any]] = []

    with pdfplumber.open(io=pdf_bytes) as pdf:
        # Collect all text for header parsing
        all_text_parts = []
        page_texts = []
        for page in pdf.pages:
            t = page.extract_text() or ""
            page_texts.append(t)
            all_text_parts.append(t)
        full_text = "\n".join(all_text_parts)

        titular, fecha_estado = _extract_header_fields(full_text)
        archivo_origen = _build_archivo_origen(filename, titular, fecha_estado)

        in_transacciones = False
        in_comisiones = False

        for t in page_texts:
            for raw_line in t.splitlines():
                line = " ".join(raw_line.split())
                if not line:
                    continue

                u = line.upper()

                # Section toggles
                if "2. INFORMACIÓN DE TRANSACCIONES" in u:
                    in_transacciones = True
                    in_comisiones = False
                    continue

                if "COMISIONES, OTROS CARGOS Y ABONOS" in u:
                    in_comisiones = True
                    in_transacciones = False
                    continue

                # Stop blocks at totals
                if u.startswith("TOTAL TARJETA"):
                    in_transacciones = False
                    # commissions may continue after, so do not change in_comisiones here
                    continue

                # Ignore header lines inside the table
                if u.startswith(("NUMERO", "FECHA", "DESCRIPCION", "CIUDAD", "PAIS", "MONTO", "TOTAL DE PAGOS", "TOTAL DE COMPRAS")):
                    continue

                # Only parse lines inside relevant sections
                if not (in_transacciones or in_comisiones):
                    continue

                if not DATE_RE.search(line):
                    continue

                row = _parse_transaction_line(line, archivo_origen)
                if row:
                    rows.append(row)

    # Deduplicate (same line might appear across page breaks / extraction artifacts)
    uniq = {}
    for r in rows:
        key = (r["FECHA_OPERACION"], r["DESCRIPCION"], r.get("PAIS",""), r["MONTO_OPERACION"], r["ARCHIVO_ORIGEN"])
        uniq[key] = r
    return list(uniq.values())
