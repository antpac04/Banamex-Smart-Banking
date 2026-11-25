"""Crea la base sintética, carga los scripts del socio (sql/000-003), aplica roles + RLS (sql/010),
instala la capa semántica del socio (sql/semantica/01-07) y la valida contra los datos (sql/020).
Idempotente: si ya está cargada solo reaplica la seguridad.
    python scripts/load_db.py            # carga si hace falta
    python scripts/load_db.py --force    # borra y regenera todo
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

import db_config as db  # noqa: E402

ESPERADO = {"cfg.fact_sdos_captacoloca_m": 120000, "cfg.fact_txn_captacoloca_d": 225000, "dim.dim_cliente": 5000}


def conteos(conn):
    try:
        return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in ESPERADO}
    except psycopg.errors.UndefinedTable:
        return None


def main(force: bool = False) -> None:
    print(f"PostgreSQL {'embebido en ' + str(db.pgdata()) if db.use_embedded() else 'externo'} · base {db.db_name()}")
    with psycopg.connect(**db.admin_conninfo("postgres"), autocommit=True) as c:
        if not c.execute("select 1 from pg_database where datname=%s", (db.db_name(),)).fetchone():
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db.db_name())))
            print("Base creada")
    with psycopg.connect(**db.admin_conninfo(db.db_name()), autocommit=True) as conn:
        actual = conteos(conn)
        if actual == ESPERADO and not force:
            print("Datos ya cargados:", actual)
        else:
            conn.execute("DROP SCHEMA IF EXISTS cfg CASCADE; DROP SCHEMA IF EXISTS dim CASCADE;")
            for f in sorted((ROOT / "sql").glob("00[0-3]_*.sql")):
                print(f"Ejecutando {f.name} (1-2 min)...", flush=True)
                conn.execute(f.read_text(encoding="utf-8"))
        print("Aplicando roles y Row Level Security (010)...")
        conn.execute((ROOT / "sql" / "010_seguridad_roles_rls.sql").read_text(encoding="utf-8"))
        semantica = ROOT / "sql" / "semantica"
        if semantica.exists():
            print("Instalando capa semántica del socio (sql/semantica)...")
            for f in sorted(semantica.glob("0[1-7]_*.sql")):
                conn.execute(f.read_text(encoding="utf-8"))
            print("Validando la capa semántica contra los datos (020)...")
            conn.execute((ROOT / "sql" / "020_validacion_capa_semantica.sql").read_text(encoding="utf-8"))
            for cod, ok, ev in conn.execute("SELECT codigo, resultado, evidencia FROM semantic.sem_validaciones ORDER BY 1"):
                print(f"   {cod}: {'OK ' if ok else 'NO '} {ev}")
            n = conn.execute("SELECT COUNT(*) FROM semantic.sem_relaciones WHERE relacion_validada").fetchone()[0]
            print(f"   Relaciones validadas para JOIN: {n}")
        else:
            print("AVISO: no existe sql/semantica (copia ahí los scripts de la capa semántica del socio).")
        if not db.use_embedded():
            for rol in (db.ROL_BD_CLIENTE, db.ROL_BD_EMPLEADO):
                conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(rol), sql.Literal(os.getenv("APP_ROLE_PASSWORD", ""))))
        print("Conteos:", conteos(conn))


if __name__ == "__main__":
    main(force="--force" in sys.argv)