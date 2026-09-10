"""Base de datos del sistema de secado (SQLite, sin dependencias externas).

El archivo vive en Sistema/secado.db. Para moverlo a una carpeta de red basta
cambiar RUTA_DB o definir la variable de entorno SECADO_DB.
"""
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_DB = os.environ.get("SECADO_DB", os.path.join(BASE, "secado.db"))
RUTA_ARCHIVOS = os.environ.get("SECADO_ARCHIVOS", os.path.join(BASE, "archivos"))

COLS_PROCESO = [
    "awm", "emc", "temperatura", "humedad_relativa", "conjunto_emc",
    "temp_programada", "temp_reducida", "ajuste_hr", "velocidad_secado",
    "sonda_1", "sonda_2", "sonda_3", "sonda_4",
    "sonda_11", "sonda_12", "sonda_13", "sonda_14", "sonda_15", "sonda_16",
]

ESQUEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ciclo (
  camara          INTEGER NOT NULL,
  ciclo           INTEGER NOT NULL,
  programa        TEXT,
  especie         TEXT,
  cliente         TEXT,
  inicio_log      TEXT,      -- primer registro del PLC
  fin_log         TEXT,
  inicio_informe  TEXT,      -- ventana que declara el informe de humedad
  fin_informe     TEXT,
  n_muestras      INTEGER,
  mc_medio        REAL,
  mc_sd           REAL,
  mc_min          REAL,
  mc_max          REAL,
  crit_objetivo   REAL DEFAULT 9,    -- humedad que persigue el secado
  crit_lo         REAL DEFAULT 8,    -- banda de aceptacion, limite inferior
  crit_hi         REAL DEFAULT 12,   -- banda de aceptacion, limite superior
  crit_umbral     REAL DEFAULT 85,
  n_bajas         INTEGER,
  n_altas         INTEGER,
  n_rango         INTEGER,
  resultado       TEXT,
  k_paquetes      INTEGER,   -- paquetes reconocidos por la regla de 24 a 26
  grupo_camara    TEXT,      -- 'p12' o 'p36'
  ambiguo         INTEGER DEFAULT 0,
  actualizado_en  TEXT DEFAULT (datetime('now','localtime')),
  PRIMARY KEY (camara, ciclo)
);

CREATE TABLE IF NOT EXISTS proceso (
  camara INTEGER NOT NULL,
  ciclo  INTEGER NOT NULL,
  ts     TEXT    NOT NULL,
  %s,
  PRIMARY KEY (camara, ciclo, ts),
  FOREIGN KEY (camara, ciclo) REFERENCES ciclo (camara, ciclo) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS muestra (
  camara    INTEGER NOT NULL,
  ciclo     INTEGER NOT NULL,
  n_muestra INTEGER NOT NULL,
  mc        REAL    NOT NULL,
  paquete   INTEGER,
  posicion  INTEGER,
  PRIMARY KEY (camara, ciclo, n_muestra),
  FOREIGN KEY (camara, ciclo) REFERENCES ciclo (camara, ciclo) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_muestra_pkg ON muestra (camara, ciclo, paquete);

-- El sha256 impide cargar dos veces el mismo archivo sin darse cuenta.
CREATE TABLE IF NOT EXISTS archivo (
  camara     INTEGER NOT NULL,
  ciclo      INTEGER NOT NULL,
  tipo       TEXT    NOT NULL,          -- 'muestras' | 'proceso'
  nombre     TEXT    NOT NULL,
  sha256     TEXT    NOT NULL,
  bytes      INTEGER,
  formato    TEXT,                      -- 'xlsx' | 'csv' | 'pdf'
  precision_decimal INTEGER DEFAULT 1,  -- 0 si viene del PDF truncado
  ruta       TEXT,
  cargado_en TEXT DEFAULT (datetime('now','localtime')),
  PRIMARY KEY (camara, ciclo, tipo),
  FOREIGN KEY (camara, ciclo) REFERENCES ciclo (camara, ciclo) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_archivo_sha ON archivo (sha256);

CREATE TABLE IF NOT EXISTS evento (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       TEXT DEFAULT (datetime('now','localtime')),
  camara   INTEGER,
  ciclo    INTEGER,
  nivel    TEXT,                        -- 'ok' | 'aviso' | 'alerta'
  mensaje  TEXT
);
""" % (",\n  ".join("%s REAL" % c for c in COLS_PROCESO))


def _migrar(cx):
    """Bases creadas antes guardaban la banda como objetivo +- tolerancia.
    Ahora se guardan los dos limites, que no tienen por que ser simetricos."""
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(ciclo)")}
    if "crit_lo" in cols:
        return
    cx.execute("ALTER TABLE ciclo ADD COLUMN crit_lo REAL DEFAULT 8")
    cx.execute("ALTER TABLE ciclo ADD COLUMN crit_hi REAL DEFAULT 12")
    if "crit_tol" in cols:
        # se conserva la banda con la que se puntuo cada ciclo; recriterio() la cambia
        cx.execute("UPDATE ciclo SET crit_lo = crit_objetivo - crit_tol,"
                   "                crit_hi = crit_objetivo + crit_tol"
                   " WHERE crit_objetivo IS NOT NULL AND crit_tol IS NOT NULL")
        cx.execute("ALTER TABLE ciclo DROP COLUMN crit_tol")
    cx.commit()


def conectar():
    os.makedirs(os.path.dirname(RUTA_DB) or ".", exist_ok=True)
    os.makedirs(RUTA_ARCHIVOS, exist_ok=True)
    cx = sqlite3.connect(RUTA_DB, timeout=20)
    cx.row_factory = sqlite3.Row
    cx.executescript(ESQUEMA)
    _migrar(cx)
    return cx


def registrar(cx, camara, ciclo, nivel, mensaje):
    cx.execute("INSERT INTO evento (camara, ciclo, nivel, mensaje) VALUES (?,?,?,?)",
               (camara, ciclo, nivel, mensaje))


def sha_ya_cargado(cx, sha):
    r = cx.execute("SELECT camara, ciclo, tipo, nombre, cargado_en FROM archivo WHERE sha256=?",
                   (sha,)).fetchone()
    return dict(r) if r else None


def ciclos(cx):
    return [dict(r) for r in cx.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM proceso p WHERE p.camara=c.camara AND p.ciclo=c.ciclo) AS n_proceso,
               (SELECT COUNT(*) FROM muestra m WHERE m.camara=c.camara AND m.ciclo=c.ciclo) AS n_muestra,
               (SELECT formato FROM archivo a WHERE a.camara=c.camara AND a.ciclo=c.ciclo
                  AND a.tipo='proceso') AS fmt_proceso
        FROM ciclo c
        ORDER BY c.ciclo DESC, c.camara""")]


def ciclo(cx, camara, num):
    r = cx.execute("SELECT * FROM ciclo WHERE camara=? AND ciclo=?", (camara, num)).fetchone()
    return dict(r) if r else None


def serie(cx, camara, num):
    cols = ", ".join(COLS_PROCESO)
    return cx.execute(
        "SELECT ts, %s FROM proceso WHERE camara=? AND ciclo=? ORDER BY ts" % cols,
        (camara, num)).fetchall()


def muestras(cx, camara, num):
    return cx.execute(
        "SELECT n_muestra, mc, paquete, posicion FROM muestra "
        "WHERE camara=? AND ciclo=? ORDER BY n_muestra", (camara, num)).fetchall()


def borrar_ciclo(cx, camara, num):
    for t in ("proceso", "muestra", "archivo"):
        cx.execute("DELETE FROM %s WHERE camara=? AND ciclo=?" % t, (camara, num))
    cx.execute("DELETE FROM ciclo WHERE camara=? AND ciclo=?", (camara, num))
