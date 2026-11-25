"""Roles, login, auditoría y guardas deterministas (no dependen del LLM).

Roles de la app:
  cliente  (usuario normal)  -> solo SUS cuentas (num_cte fijo desde el login) + documentos públicos
  empleado (administrador)   -> toda la base sin datos personales + documentos internos + auditoría

Uso por terminal:
  python src/auth.py add ana.steward empleado      # crea/actualiza un empleado (pide contraseña)
  python src/auth.py demo                          # crea los usuarios demo
  python src/auth.py list
"""
import functools
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass

import common

ROL_CLIENTE = "cliente"
ROL_EMPLEADO = "empleado"
ROLES = (ROL_CLIENTE, ROL_EMPLEADO)


@dataclass(frozen=True)
class Identidad:
    rol: str
    usuario: str
    num_cte: int | None = None
    nombre: str = ""

    @property
    def es_cliente(self) -> bool:
        return self.rol == ROL_CLIENTE

    def env(self) -> dict:
        """Variables con las que se lanzan los servidores MCP de ESTA sesión."""
        e = {"STEWARD_ROLE": self.rol, "STEWARD_USER": self.usuario}
        if self.num_cte is not None:
            e["STEWARD_NUM_CTE"] = str(self.num_cte)
        return e


def identidad_desde_env() -> Identidad:
    """Lo usan los servidores MCP. Rol inválido o ausente -> cliente sin num_cte (no ve nada)."""
    rol = os.getenv("STEWARD_ROLE", ROL_CLIENTE)
    if rol not in ROLES:
        rol = ROL_CLIENTE
    num = os.getenv("STEWARD_NUM_CTE")
    return Identidad(rol, os.getenv("STEWARD_USER", "desconocido"), int(num) if num else None)


# ------------------------------------------------------------------ usuarios (DEMO)
def _hash(secreto: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", secreto.encode(), salt.encode(), 100_000).hex()


def _cargar() -> dict:
    if not common.USERS_FILE.exists():
        crear_demo()
    return json.loads(common.USERS_FILE.read_text(encoding="utf-8"))


def _guardar(data: dict) -> None:
    common.USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    common.USERS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def crear_demo() -> None:
    """Empleados ana.steward / luis.analista (Banamex2026!) y clientes 1-5000 con PIN 1234."""
    data = {"empleados": [], "clientes_demo": {}}
    for u, n in [("ana.steward", "Ana (Data Steward)"), ("luis.analista", "Luis (Analista)")]:
        s = secrets.token_hex(8)
        data["empleados"].append({"usuario": u, "nombre": n, "salt": s, "hash": _hash("Banamex2026!", s)})
    s = secrets.token_hex(8)
    data["clientes_demo"] = {"num_cte_min": 1, "num_cte_max": 5000, "salt": s, "hash_pin": _hash("1234", s)}
    _guardar(data)


def login_empleado(usuario: str, password: str) -> Identidad | None:
    for e in _cargar()["empleados"]:
        if e["usuario"] == usuario and _hash(password, e["salt"]) == e["hash"]:
            return Identidad(ROL_EMPLEADO, usuario, None, e.get("nombre", usuario))
    return None


def login_cliente(num_cte: int, pin: str) -> Identidad | None:
    c = _cargar()["clientes_demo"]
    if not (c["num_cte_min"] <= int(num_cte) <= c["num_cte_max"]) or _hash(pin, c["salt"]) != c["hash_pin"]:
        return None
    return Identidad(ROL_CLIENTE, f"cliente-{num_cte}", int(num_cte), f"Cliente {num_cte}")


# ------------------------------------------------------------------ auditoría
def auditar(ident: Identidad, accion: str, permitido: bool, **detalle) -> None:
    common.AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    reg = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "usuario": ident.usuario, "rol": ident.rol,
           "num_cte": ident.num_cte, "accion": accion, "permitido": permitido, **detalle}
    with common.AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")


def guarded(*roles_permitidos: str):
    """Decorador para tools MCP: revalida el rol del proceso y audita cada llamada."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ident = identidad_desde_env()
            if ident.rol not in roles_permitidos:
                auditar(ident, fn.__name__, False, args=kwargs)
                return f"ACCESO DENEGADO: el rol '{ident.rol}' no puede usar {fn.__name__}."
            auditar(ident, fn.__name__, True, args=kwargs)
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ------------------------------------------------------------------ guarda de entrada
_INYECCION = [
    r"ignora (todas )?(tus|las) (instrucciones|reglas)", r"ignore (all |your |previous )+instructions",
    r"olvida (tus|las) (instrucciones|reglas)", r"(muestra|revela|dime) (tu|el) (prompt|system prompt|instrucciones)",
    r"system prompt", r"modo (desarrollador|dios|admin)", r"jailbreak",
    r"(ahora )?eres (un )?(administrador|empleado|admin)", r"act[uú]a como (administrador|empleado|admin)",
    r"(drop|delete|truncate|update|insert)\s+(table|from|into)",
]


def detectar_inyeccion(texto: str) -> str | None:
    for p in _INYECCION:
        if re.search(p, texto, flags=re.IGNORECASE):
            return p
    return None


# ------------------------------------------------------------------ guarda SQL
_PROHIBIDAS = (r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|vacuum|"
               r"analyze|comment|security|set|reset|listen|notify|lock|prepare|refresh|reindex|cluster|pg_sleep|"
               r"pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|dblink|set_config)\b")


class SQLRechazado(ValueError):
    pass


def validar_sql(consulta: str) -> str:
    """UNA sentencia SELECT/WITH. 2a capa: la 1a es el rol de BD de solo lectura."""
    sql = re.sub(r"--[^\n]*", " ", consulta or "")
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL).strip().rstrip(";").strip()
    if not sql:
        raise SQLRechazado("Consulta vacía.")
    if ";" in sql:
        raise SQLRechazado("Solo se permite una sentencia.")
    if not re.match(r"^(select|with)\b", sql, flags=re.IGNORECASE):
        raise SQLRechazado("Solo se permiten consultas SELECT (o WITH ... SELECT).")
    m = re.search(_PROHIBIDAS, re.sub(r"'(?:[^']|'')*'", "''", sql), flags=re.IGNORECASE)
    if m:
        raise SQLRechazado(f"Palabra no permitida: {m.group(0)}")
    return sql


# ------------------------------------------------------------------ guarda de salida
_SALIDA = [
    (re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b"), "[CURP oculta]"),
    (re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b"), "[RFC oculto]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[correo oculto]"),
]


def filtrar_salida(texto: str) -> str:
    """Oculta tarjetas/CLABE (12-19 dígitos), CURP, RFC y correos antes de mostrar la respuesta."""
    texto = re.sub(r"\b(?:\d[ -]?){12,19}\b", lambda m: "****" + re.sub(r"\D", "", m.group(0))[-4:], texto)
    for rx, rep in _SALIDA:
        texto = rx.sub(rep, texto)
    return texto


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "demo":
        crear_demo()
        print("Usuarios demo creados en", common.USERS_FILE)
    elif cmd == "add" and len(sys.argv) >= 3:
        data = _cargar()
        usuario = sys.argv[2]
        pwd = getpass.getpass("Contraseña: ")
        s = secrets.token_hex(8)
        data["empleados"] = [e for e in data["empleados"] if e["usuario"] != usuario]
        data["empleados"].append({"usuario": usuario, "nombre": usuario, "salt": s, "hash": _hash(pwd, s)})
        _guardar(data)
        print("Empleado guardado:", usuario)
    else:
        d = _cargar()
        print("Empleados:", [e["usuario"] for e in d["empleados"]])
        print("Clientes demo: num_cte", d["clientes_demo"]["num_cte_min"], "a", d["clientes_demo"]["num_cte_max"])
