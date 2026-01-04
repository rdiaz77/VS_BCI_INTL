import sqlite3
from pathlib import Path
from typing import Iterable, Dict, Any, List, Tuple


def init_db(db_path: str) -> sqlite3.Connection:
    """Create/connect SQLite DB and ensure tables exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transacciones (
            FECHA_OPERACION TEXT,
            DESCRIPCION TEXT,
            CIUDAD TEXT,
            PAIS TEXT,
            REF_INTERNACIONAL TEXT,
            MONTO_ORIGEN REAL,
            MONTO_OPERACION REAL,
            MONTO_TOTAL REAL,
            TIPO_GASTO TEXT,
            FACT_KAME INTEGER DEFAULT 0,
            ARCHIVO_ORIGEN TEXT,
            CONCILIADO INTEGER DEFAULT 0
        );
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archivos_procesados (
            nombre TEXT PRIMARY KEY,
            fecha_procesado TEXT DEFAULT (datetime('now'))
        );
        """
    )

    conn.commit()
    return conn


def archivo_ya_procesado(conn: sqlite3.Connection, filename: str) -> bool:
    cur = conn.execute("SELECT 1 FROM archivos_procesados WHERE nombre = ? LIMIT 1", (filename,))
    return cur.fetchone() is not None


def registrar_archivo_procesado(conn: sqlite3.Connection, filename: str) -> None:
    conn.execute("INSERT OR IGNORE INTO archivos_procesados(nombre) VALUES (?)", (filename,))
    conn.commit()


def insertar_en_db(conn: sqlite3.Connection, rows: Iterable[Dict[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0

    conn.executemany(
        """
        INSERT INTO transacciones(
            FECHA_OPERACION, DESCRIPCION, CIUDAD, PAIS, REF_INTERNACIONAL,
            MONTO_ORIGEN, MONTO_OPERACION, MONTO_TOTAL,
            TIPO_GASTO, FACT_KAME, ARCHIVO_ORIGEN, CONCILIADO
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        [
            (
                r.get("FECHA_OPERACION", ""),
                r.get("DESCRIPCION", ""),
                r.get("CIUDAD", ""),
                r.get("PAIS", ""),
                r.get("REF_INTERNACIONAL", ""),
                r.get("MONTO_ORIGEN", None),
                r.get("MONTO_OPERACION", None),
                r.get("MONTO_TOTAL", None),
                r.get("TIPO_GASTO", ""),
                int(r.get("FACT_KAME", 0)),
                r.get("ARCHIVO_ORIGEN", ""),
                int(r.get("CONCILIADO", 0)),
            )
            for r in rows
        ],
    )
    conn.commit()
    return len(rows)


def fetch_all(conn: sqlite3.Connection) -> Tuple[List[str], List[tuple]]:
    cur = conn.execute("SELECT rowid AS _RID_, * FROM transacciones")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return cols, rows


def update_rows(conn: sqlite3.Connection, updates: List[Dict[str, Any]]) -> None:
    """
    Update rows by rowid (_RID_). Expected keys:
      _RID_, TIPO_GASTO, CONCILIADO
    """
    conn.executemany(
        """
        UPDATE transacciones
        SET TIPO_GASTO = ?, CONCILIADO = ?
        WHERE rowid = ?;
        """,
        [
            (
                (u.get("TIPO_GASTO") or ""),
                int(bool(u.get("CONCILIADO"))),
                int(u["_RID_"]),
            )
            for u in updates
        ],
    )
    conn.commit()


def mark_rows_as_kame(conn: sqlite3.Connection, rowids: List[int]) -> None:
    if not rowids:
        return
    conn.executemany(
        """
        UPDATE transacciones
        SET FACT_KAME = 1
        WHERE rowid = ?;
        """,
        [(int(rid),) for rid in rowids],
    )
    conn.commit()


def reset_db(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM transacciones;")
    conn.execute("DELETE FROM archivos_procesados;")
    conn.commit()
