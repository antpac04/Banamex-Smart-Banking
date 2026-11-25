"""PostgreSQL: embebido (pixeltable-pgserver, sin Docker) o externo (USE_EMBEDDED_DB=0 + PG*).

Roles de BD (los crea sql/010_seguridad_roles_rls.sql vía scripts/load_db.py):
  steward_cliente  -> solo hechos/catálogos con ROW LEVEL SECURITY por num_cte
  steward_empleado -> todo menos columnas personales (fec_nac, genero_cte)
"""
import os
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

import common  # noqa: F401  (carga .env)

ROL_BD_CLIENTE = "steward_cliente"
ROL_BD_EMPLEADO = "steward_empleado"
COLUMNAS_PII = ("fec_nac", "genero_cte")

_server = None


def use_embedded() -> bool:
    return os.getenv("USE_EMBEDDED_DB", "1") == "1"


def db_name() -> str:
    return os.getenv("POSTGRES_DB", "banco_sintetico")


def pgdata() -> Path:
    base = os.getenv("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(os.getenv("PGDATA_DIR", str(Path(base) / "data-steward" / "pgdata")))


def ensure_db():
    """Arranca el PostgreSQL embebido si hace falta (no hace nada en modo externo)."""
    global _server
    if use_embedded() and _server is None:
        import pixeltable_pgserver

        pgdata().mkdir(parents=True, exist_ok=True)
        _server = pixeltable_pgserver.get_server(str(pgdata()))
    return _server


def ensure_db_silencioso():
    """Para servidores MCP por stdio: cualquier print del arranque de PostgreSQL rompería el protocolo,
    así que se manda stdout (también el de procesos hijos) a stderr mientras arranca."""
    import sys

    sys.stdout.flush()
    copia = os.dup(1)
    os.dup2(2, 1)
    try:
        return ensure_db()
    finally:
        sys.stdout.flush()
        os.dup2(copia, 1)
        os.close(copia)


def stop_db():
    srv = ensure_db()
    if srv is not None:
        srv.cleanup()


def _base() -> dict:
    if use_embedded():
        return conninfo_to_dict(ensure_db().get_uri())
    return {"host": os.getenv("PGHOST", "localhost"), "port": os.getenv("PGPORT", "5432"),
            "user": os.getenv("PGUSER", "postgres"), "password": os.getenv("PGPASSWORD", "")}


def admin_conninfo(dbname: str) -> dict:
    return {**_base(), "dbname": dbname}


def role_conninfo(rol: str) -> dict:
    info = {**_base(), "dbname": db_name(), "user": rol}
    if use_embedded():
        info.pop("password", None)  # el embebido usa auth 'trust'
    else:
        info["password"] = os.getenv("APP_ROLE_PASSWORD", "")
    return info


def consultar(sql: str, params=None, *, rol: str, num_cte: int | None = None, max_filas: int | None = None):
    """SELECT en transacción de SOLO LECTURA con el rol indicado. Para el cliente fija app.num_cte
    (la RLS de la base filtra las filas). Devuelve (columnas, filas, truncado)."""
    max_filas = max_filas or common.MAX_FILAS
    with psycopg.connect(**role_conninfo(rol), connect_timeout=15) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '15s'")
        if rol == ROL_BD_CLIENTE:
            if num_cte is None:
                raise PermissionError("Consulta de cliente sin num_cte de sesión")
            conn.execute("SELECT set_config('app.num_cte', %s, true)", (str(int(num_cte)),))
        cur = conn.execute(sql, params or None)  # None: un "%" literal (LIKE) no se toma como parámetro
        cols = [d.name for d in cur.description] if cur.description else []
        filas = cur.fetchmany(max_filas + 1)
        conn.rollback()
    return cols, filas[:max_filas], len(filas) > max_filas


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return f"{v:,.2f}"
    return str(v)


def a_markdown(cols, filas, truncado=False) -> str:
    if not filas:
        return "(sin filas)"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(_fmt(v) for v in f) + " |" for f in filas]
    if truncado:
        out.append(f"\n(Resultado truncado a {common.MAX_FILAS} filas)")
    return "\n".join(out)
