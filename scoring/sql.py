"""DuckDB result helpers shared by the API and the scoring package.

Lifted out of app.py unchanged so scoring/ does not import the app.
"""

_NUMERIC = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
            "UINTEGER", "UBIGINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL"}


def num(v, default=0.0) -> float:
    """AVG() over zero rows is SQL NULL, which reaches us as None from
    fetchone() tuples and as NaN from rows() dicts. Guard both."""
    return default if v is None or v != v else float(v)


def safe(s: str) -> str:
    return s.replace("'", "''")


def rows(cur) -> list[dict]:
    """SQL NULL -> NaN in numeric columns, so the `x == x` guards keep behaving
    exactly as they did with pandas DataFrames."""
    cols = [d[0] for d in cur.description]
    numeric = {i for i, d in enumerate(cur.description)
               if str(d[1]).split("(")[0] in _NUMERIC}
    nan = float("nan")
    return [
        {c: (nan if (i in numeric and v is None) else v)
         for i, (c, v) in enumerate(zip(cols, row))}
        for row in cur.fetchall()
    ]
