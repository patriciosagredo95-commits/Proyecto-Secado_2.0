"""Servidor local del sistema de secado. Sin dependencias fuera de la
biblioteca estandar (openpyxl solo se usa al leer un .xlsx).

    python servidor.py            -> http://localhost:8765
    python servidor.py 8080       -> otro puerto

Para publicarlo en la red de planta, ejecutalo en el equipo servidor y abre el
puerto: los demas entran con http://<ip-del-equipo>:8765
"""
import json
import os
import sys
import tempfile
import threading
import traceback
import urllib.parse as up
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db
import ingesta
import tablero

BASE = os.path.dirname(os.path.abspath(__file__))
TEMP = os.path.join(BASE, "temp")
MAX_SUBIDA = 80 * 1024 * 1024
PLANO = "propuesta_2_plano_camaras_v3.html"
_local = threading.local()


def cx():
    if not hasattr(_local, "cx"):
        _local.cx = db.conectar()
    return _local.cx


# --------------------------------------------------------------- handler
class H(BaseHTTPRequestHandler):
    server_version = "Secado/1.0"

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s %s\n" % (self.command, self.path))

    # -- helpers
    def _env(self, code, tipo, cuerpo):
        if isinstance(cuerpo, str):
            cuerpo = cuerpo.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, obj, code=200):
        self._env(code, "application/json; charset=utf-8",
                  json.dumps(obj, ensure_ascii=False))

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_SUBIDA:
            raise ingesta.ErrorIngesta("El archivo supera los 80 MB.")
        leido, trozos = 0, []
        while leido < n:
            t = self.rfile.read(min(1 << 20, n - leido))
            if not t:
                break
            trozos.append(t)
            leido += len(t)
        return b"".join(trozos)

    # -- rutas
    def do_GET(self):
        u = up.urlparse(self.path)
        q = up.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html", "/tablero"):
                lista = db.ciclos(cx())
                conproc = [c for c in lista if c["n_proceso"]]
                if q.get("camara") and q.get("ciclo"):
                    cam, cic = int(q["camara"][0]), int(q["ciclo"][0])
                elif conproc:
                    cam, cic = conproc[0]["camara"], conproc[0]["ciclo"]
                else:
                    cam = cic = None
                if cam is None:
                    return self._env(200, "text/html; charset=utf-8",
                                     tablero.render_vacio(lista))
                html = tablero.render(cx(), cam, cic, lista)
                if not html:
                    return self._env(200, "text/html; charset=utf-8", tablero.render_vacio(
                        lista, ("Cámara %d · Ciclo %d sin programa de secado" % (cam, cic),
                                "Este ciclo tiene las muestras cargadas pero le falta el archivo "
                                "del PLC, así que todavía no se puede dibujar la curva ni el "
                                "balance de horas. Cárgalo en el panel de arriba.")))
                return self._env(200, "text/html; charset=utf-8", html)
            if u.path == "/api/ciclos":
                return self._json(db.ciclos(cx()))
            if u.path == "/api/eventos":
                r = cx().execute("SELECT * FROM evento ORDER BY id DESC LIMIT 60").fetchall()
                return self._json([dict(x) for x in r])
            if u.path == "/api/original":
                cam, cic = int(q["camara"][0]), int(q["ciclo"][0])
                r = cx().execute("SELECT ruta, nombre FROM archivo WHERE camara=? AND ciclo=? AND tipo=?",
                                 (cam, cic, q["tipo"][0])).fetchone()
                if not r or not os.path.exists(r["ruta"]):
                    return self._json({"error": "No está guardado ese archivo."}, 404)
                with open(r["ruta"], "rb") as f:
                    datos = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % r["nombre"])
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                return self.wfile.write(datos)
            # el plano de planta, tal cual el archivo original de la propuesta
            if u.path == "/plano":
                for f in (os.path.join(BASE, PLANO),
                          os.path.join(os.path.dirname(BASE), PLANO)):
                    if os.path.exists(f):
                        with open(f, "rb") as h:
                            return self._env(200, "text/html; charset=utf-8", h.read())
                return self._env(404, "text/html; charset=utf-8",
                                 "<meta charset='utf-8'><body style='font:16px system-ui;"
                                 "padding:48px'><p>No se encontró <code>%s</code>. Déjalo en la "
                                 "carpeta del proyecto o dentro de <code>Sistema/</code>.</p>"
                                 "<p><a href='/'>&larr; Volver</a></p></body>" % PLANO)
            # el logo: si dejas Logo_Glover.png/.svg/.jpg junto a servidor.py,
            # la pagina lo usa en vez del dibujo de respaldo
            if u.path.lower().lstrip("/").startswith("logo_glover."):
                f = os.path.join(BASE, os.path.basename(u.path))
                if os.path.exists(f):
                    ext = os.path.splitext(f)[1].lower()
                    mime = {".svg": "image/svg+xml", ".png": "image/png",
                            ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
                    with open(f, "rb") as h:
                        return self._env(200, mime, h.read())
                return self._env(404, "text/plain; charset=utf-8", "sin logo")
            return self._env(404, "text/plain; charset=utf-8", "No existe esa ruta.")
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        u = up.urlparse(self.path)
        q = up.parse_qs(u.query)
        try:
            if u.path == "/api/inspeccionar":
                return self._inspeccionar(q)
            if u.path == "/api/confirmar":
                return self._confirmar(json.loads(self._cuerpo().decode("utf-8")))
            if u.path == "/api/borrar":
                d = json.loads(self._cuerpo().decode("utf-8"))
                db.borrar_ciclo(cx(), int(d["camara"]), int(d["ciclo"]))
                cx().commit()
                return self._json({"ok": True})
            return self._json({"error": "No existe esa ruta."}, 404)
        except ingesta.ErrorIngesta as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            return self._json({"error": "%s: %s" % (type(e).__name__, e)}, 500)

    # -- paso 1: mirar el archivo y decir que trae, sin escribir en la base
    def _inspeccionar(self, q):
        os.makedirs(TEMP, exist_ok=True)
        nombre = q.get("nombre", ["archivo"])[0]
        tipo = q.get("tipo", ["muestras"])[0]
        ext = os.path.splitext(nombre)[1].lower() or ".dat"
        datos = self._cuerpo()
        if not datos:
            raise ingesta.ErrorIngesta("No llegó ningún archivo.")
        fd, ruta = tempfile.mkstemp(suffix=ext, dir=TEMP)
        with os.fdopen(fd, "wb") as f:
            f.write(datos)

        sha = ingesta.sha256(ruta)
        ya = db.sha_ya_cargado(cx(), sha)
        r = {"token": os.path.basename(ruta), "nombre": nombre, "tipo": tipo,
             "duplicado": ya, "avisos": []}
        if tipo == "muestras":
            m = ingesta.leer_muestras(ruta)
            det = ingesta.detectar(len(m["valores"]))
            r.update(ciclo=m.get("ciclo"), n=len(m["valores"]), formato=m["formato"],
                     deteccion=det, grupo=ingesta.NOMBRE_GRUPO[det["grupo"]],
                     k=ingesta.k_preferido(det, det["grupo"]))
            if not det["ok"]:
                r["avisos"].append(["alerta",
                    "%d muestras necesitan al menos %d paquetes y la cámara mayor admite %d. "
                    "El archivo trae más de una carga o el Wagner duplicó los datos."
                    % (det["n"], det["kmin"], ingesta.CAP["p36"])])
            elif det["ambiguo"]:
                r["avisos"].append(["aviso",
                    "Entre %d y %d paquetes: cabe en cámaras 1–2 y en 3–6, hay que elegir."
                    % (det["kmin"], det["kmax"])])
            else:
                r["avisos"].append(["ok",
                    "Entre %d y %d paquetes: más de %d sólo cabe en %s."
                    % (det["kmin"], det["kmax"], ingesta.CAP["p12"], ingesta.NOMBRE_GRUPO["p36"])])
        else:
            p = ingesta.leer_proceso(ruta, nombre)
            r.update(camara=p["camara"], n=len(p["filas"]), formato=p["formato"],
                     precision=p["precision"],
                     desde=p["filas"][0][0], hasta=p["filas"][-1][0])
            r["avisos"].append(["ok" if p["precision"] else "aviso",
                "%d registros del PLC con precisión completa." % len(p["filas"]) if p["precision"]
                else "El PDF trunca cada celda a 3 caracteres y los valores de dos dígitos pierden "
                     "el decimal. Si existe el .xlsx del PLC, cárgalo en su lugar."])
        if ya:
            r["avisos"].insert(0, ["aviso",
                "Este archivo ya se cargó el %s en la cámara %d, ciclo %d."
                % (ya["cargado_en"], ya["camara"], ya["ciclo"])])
        return self._json(r)

    # -- paso 2: confirmar camara y ciclo, y escribir
    def _confirmar(self, d):
        cam, cic = int(d["camara"]), int(d["ciclo"])
        rutas = {}
        for k in ("muestras", "proceso"):
            tok = d.get(k)
            if tok:
                p = os.path.join(TEMP, os.path.basename(tok))
                if not os.path.exists(p):
                    raise ingesta.ErrorIngesta("Se perdió el archivo de %s; vuelve a subirlo." % k)
                rutas[k] = p
        if not rutas:
            raise ingesta.ErrorIngesta("No hay ningún archivo que cargar.")
        res = ingesta.guardar(cx(), cam, cic,
                              muestras_ruta=rutas.get("muestras"),
                              proceso_ruta=rutas.get("proceso"),
                              nombres={"muestras": d.get("nombre_muestras"),
                                       "proceso": d.get("nombre_proceso")},
                              objetivo=float(d.get("objetivo", 9)),
                              lo=float(d.get("lo", 8)),
                              hi=float(d.get("hi", 12)),
                              umbral=float(d.get("umbral", 85)))
        for p in rutas.values():
            try:
                os.remove(p)
            except OSError:
                pass
        res["camara"], res["ciclo"] = cam, cic
        res["tablero"] = "/?camara=%d&ciclo=%d" % (cam, cic)
        res["deteccion"] = None      # ya se informo al inspeccionar
        return self._json(res)


def main():
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    db.conectar().close()
    tablero.puerto(puerto)
    srv = ThreadingHTTPServer(("0.0.0.0", puerto), H)
    url = "http://localhost:%d/" % puerto
    print("Sistema de secado")
    print("  En este equipo   : %s" % url)
    print("  Desde la planta  : %s" % tablero.url_red())
    print("  Base de datos    : %s" % db.RUTA_DB)
    print("Ctrl+C para detener.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")


if __name__ == "__main__":
    main()
