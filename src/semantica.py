"""Capa semántica del socio (esquema `semantic`) usada en tiempo de ejecución.

1. guia_desde_catalogo(): arma la guía del modelo de datos que lee el agente con las tablas, columnas,
   métricas, reglas y relaciones VALIDADAS del catálogo (en vez de un texto escrito a mano).
2. validar_contra_catalogo(): revisa una consulta antes de ejecutarla, aplicando las reglas del socio:
   - tablas y columnas deben existir en sem_tablas / sem_columnas
   - columnas restringidas prohibidas
   - R005: solo JOIN entre tablas con relación validada (y llave compuesta en dim_txn)
   - R001: no sumar saldos (snapshots) de varios meses
   - R007: no unir dos tablas de hechos sin preagregar
   - R011: no agrupar por el campo 'dominio' del hecho
"""
import re

ESQUEMA_FISICO = {"dim_cliente": "dim", "dim_producto": "dim", "dim_txn": "dim",
                  "fact_sdos_captacoloca_m": "cfg", "fact_txn_captacoloca_d": "cfg"}
HECHOS = {"fact_sdos_captacoloca_m", "fact_txn_captacoloca_d"}
RESTRINGIDAS = {"fec_nac", "genero_cte"}  # política interna: clasificación Restringida

_CACHE: dict | None = None


class ViolacionSemantica(ValueError):
    pass


# ------------------------------------------------------------------ carga del catálogo
def cargar_catalogo(consultar) -> dict | None:
    """consultar(sql) -> (cols, filas, trunc). Devuelve None si la capa semántica no está instalada."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        _, tablas, _ = consultar("""SELECT nombre_tabla, nombre_negocio, granularidad, restricciones
                                    FROM semantic.sem_tablas WHERE activo ORDER BY tipo_tabla DESC, nombre_tabla""")
        _, cols, _ = consultar("""SELECT t.nombre_tabla, c.nombre_columna, c.tipo_dato_fisico, c.nombre_negocio,
                                         c.sensibilidad, c.sql_generation_hints, c.ejemplos_valores::text, c.nivel_confianza
                                  FROM semantic.sem_columnas c JOIN semantic.sem_tablas t USING (tabla_id)
                                  WHERE c.activo ORDER BY t.nombre_tabla, c.columna_id""")
        _, mets, _ = consultar("""SELECT m.codigo_metrica, m.nombre_metrica, t.nombre_tabla, m.formula_sql,
                                         m.comportamiento_temporal, m.restricciones
                                  FROM semantic.sem_metricas m JOIN semantic.sem_tablas t ON t.tabla_id = m.tabla_origen
                                  WHERE m.activo ORDER BY 1""")
        _, reglas, _ = consultar("""SELECT codigo_regla, nombre_regla, instruccion_sql FROM semantic.sem_reglas_negocio
                                    WHERE activo ORDER BY prioridad""")
        _, rels, _ = consultar("""SELECT r.nombre_relacion, a.nombre_tabla, b.nombre_tabla, r.condicion_join
                                  FROM semantic.sem_relaciones r
                                  JOIN semantic.sem_tablas a ON a.tabla_id = r.tabla_origen
                                  JOIN semantic.sem_tablas b ON b.tabla_id = r.tabla_destino
                                  WHERE r.activo AND r.relacion_validada""")
    except Exception:  # noqa: BLE001  (esquema semantic no instalado)
        return None
    cat = {"tablas": {t: {"negocio": n, "grano": g, "restricciones": r} for t, n, g, r in tablas},
           "columnas": {}, "metricas": mets, "reglas": reglas,
           "relaciones": [(a, b, cond) for _, a, b, cond in rels]}
    for t, c, tipo, neg, sens, hint, ej, conf in cols:
        cat["columnas"].setdefault(t, {})[c] = {"tipo": tipo, "negocio": neg, "sensibilidad": sens, "hint": hint,
                                                "ejemplos": ej, "confianza": conf}
    _CACHE = cat
    return cat


# ------------------------------------------------------------------ guía para el agente
def guia_desde_catalogo(cat: dict) -> str:
    out = ["MODELO DE DATOS (capa semántica del socio; datos ene-jun 2026). Usa nombres con esquema: "
           "dim.<tabla> para dimensiones, cfg.<tabla> para hechos.", ""]
    for t, info in cat["tablas"].items():
        out.append(f"{ESQUEMA_FISICO.get(t, '?')}.{t} — {info['negocio']}. Grano: {info['grano']}")
        for c, ci in cat["columnas"].get(t, {}).items():
            if c in RESTRINGIDAS:
                out.append(f"    {c}: RESTRINGIDA (no consultable)")
                continue
            extra = f"; valores: {ci['ejemplos']}" if ci["ejemplos"] not in ("[]", None) else ""
            out.append(f"    {c} ({ci['tipo']}): {ci['negocio']}{extra}")
        if info["restricciones"]:
            out.append(f"    NOTA: {info['restricciones']}")
    out += ["", "MÉTRICAS OFICIALES:"]
    out += [f"  {cod} {nom} = {formula} sobre {tabla} ({temp}). {rest or ''}" for cod, nom, tabla, formula, temp, rest in cat["metricas"]]
    out += ["", "REGLAS OBLIGATORIAS:"]
    out += [f"  {cod} {nom}: {instr}" for cod, nom, instr in cat["reglas"]]
    out += ["", "JOINS PERMITIDOS (únicos validados; cualquier otro será rechazado):"]
    out += [f"  {a} -> {b}: {cond}" for a, b, cond in cat["relaciones"]]
    return "\n".join(out)


# ------------------------------------------------------------------ validación de SQL
def _tablas_en(sql: str) -> list[str]:
    ctes = set(re.findall(r"(?:\bwith\s+|,\s*)(\w+)\s+as\s*\(", sql, flags=re.IGNORECASE))
    tablas = []
    for esquema, nombre in re.findall(r"\b(?:from|join)\s+(?:(\w+)\.)?(\w+)", sql, flags=re.IGNORECASE):
        if nombre.lower() in ctes or nombre.lower() == "lateral":
            continue
        tablas.append((esquema.lower(), nombre.lower()))
    return tablas


def validar_contra_catalogo(sql: str, cat: dict) -> None:
    """Lanza ViolacionSemantica con un mensaje que el agente puede usar para corregir la consulta."""
    s = sql.lower()
    usadas = _tablas_en(sql)
    fisicas = []
    for esquema, t in usadas:
        if esquema == "semantic":
            continue  # consultar metadatos está permitido
        if t not in cat["tablas"]:
            raise ViolacionSemantica(f"La tabla '{t}' no existe en la capa semántica. Tablas válidas: "
                                     + ", ".join(f"{ESQUEMA_FISICO[x]}.{x}" for x in cat["tablas"]))
        fisicas.append(t)

    columnas_validas = {c for cols in cat["columnas"].values() for c in cols}
    alias_definidos = set(re.findall(r"\bas\s+(\w+)", s)) | {a for a in re.findall(r"\)\s+(\w+)", s)}
    for col in re.findall(r"\b\w+\.(\w+)\b", s):
        if col in RESTRINGIDAS:
            raise ViolacionSemantica(f"'{col}' es un dato personal restringido y no se puede consultar.")
        if col not in columnas_validas and col not in alias_definidos and col not in cat["tablas"] \
                and col not in ESQUEMA_FISICO and not col.startswith("sem_"):
            raise ViolacionSemantica(f"La columna '{col}' no existe en la capa semántica.")
    if any(re.search(rf"\b{c}\b", s) for c in RESTRINGIDAS):
        raise ViolacionSemantica("La consulta usa un dato personal restringido (fec_nac o genero_cte).")

    # R005: cada tabla adicional debe tener relación validada con alguna otra de la consulta
    unicas = list(dict.fromkeys(fisicas))
    if len(unicas) > 1:
        pares = {frozenset((a, b)) for a, b, _ in cat["relaciones"]}
        for t in unicas:
            if not any(frozenset((t, o)) in pares for o in unicas if o != t):
                if t in HECHOS and len(HECHOS & set(unicas)) == 2:
                    continue  # se revisa con R007
                raise ViolacionSemantica(f"R005: no hay relación validada para unir '{t}' con las otras tablas.")
    if "dim_txn" in unicas and "fact_txn_captacoloca_d" in unicas and \
            not re.search(r"cve_producto\s*=\s*\w*\.?cve_producto[\s\S]*cve_txn|cve_txn[\s\S]*cve_producto\s*=", s):
        raise ViolacionSemantica("R005: dim_txn se une con la llave compuesta (cve_producto, cve_txn); cve_txn sola no es única.")
    # R007: dos hechos juntos solo si al menos uno viene preagregado (subconsulta/CTE con GROUP BY)
    if len(HECHOS & set(unicas)) == 2 and s.count("group by") < 2:
        raise ViolacionSemantica("R007: para combinar saldos y transacciones preagrega cada hecho (CTE con GROUP BY) antes de unirlos.")
    # R001: no sumar snapshots de varios meses
    if re.search(r"sum\s*\(\s*(\w+\.)?saldo_(mes|apertura)", s):
        un_corte = re.search(r"fec_informacion\s*(/\s*100\s*)?=\s*\d", s)
        por_mes = re.search(r"group by[\s\S]*fec_informacion", s)
        if not (un_corte or por_mes):
            raise ViolacionSemantica("R001: los saldos son fotografías mensuales; filtra un solo fec_informacion "
                                     "(ej. = 20260630) o agrupa por fec_informacion. No sumes varios meses.")
    # R011: no agrupar por el campo dominio del hecho
    if re.search(r"group by[^;]*\b(\w+\.)?dominio\b", s) and "cve_dominio" not in s:
        raise ViolacionSemantica("R011: 'dominio' del hecho es inconsistente entre meses; agrupa por cve_producto "
                                 "o por dim_producto.cve_dominio.")