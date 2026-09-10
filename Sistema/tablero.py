"""Arma la pagina unica del sistema: panel de carga + tablero del ciclo.

Todo sale de la base de datos. Los fragmentos de plantilla/ se componen aqui y
se les inyectan los dos payloads que espera el JavaScript (D = proceso del
ciclo, RAW = muestras).
"""
import json
import os
import socket
import statistics as st
from datetime import datetime, timedelta

import db

BASE = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(BASE, "plantilla")
PASO = 5           # submuestreo de la serie, en minutos
COLA_PTS = 0.8     # cuanto AWM define la "cola" al final del ciclo
# El acondicionamiento se detecta con la consigna de EMC del programa, no con la
# fecha del informe de humedad: esa fecha marca cuando se midieron las tablas y
# es la misma para ciclos distintos. Mientras la camara acondiciona, el programa
# pide un EMC alto (17 a 26 en los ciclos vistos); al empezar a secar lo baja de
# golpe a 9-13 y ya no lo sube. Umbral verificado en los ciclos 3362, 3366 y
# 3367: entre 10 y 13 da el mismo instante con menos de una hora de diferencia.
EMC_SECADO = 12.0    # consigna de EMC bajo la cual se considera que ya seca
EMC_VUELTA = 15.0    # si vuelve sobre esto, aun estaba acondicionando
EMC_PERSIST = 12.0   # horas que debe sostenerse para no confundir un transitorio
_PUERTO = [8765]


def puerto(p):
    _PUERTO[0] = p


def url_red():
    """Direccion con la que entran los demas equipos de la planta."""
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass
    return "http://%s:%d" % (ip, _PUERTO[0])


def _dt(s):
    return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S") if s else None


def _h(a, b):
    return (b - a).total_seconds() / 3600.0


def _frag(n):
    with open(os.path.join(PLANTILLA, n), encoding="utf-8") as f:
        return f.read()


# ----------------------------------------------------------------- payload
def inicio_secado(R):
    """Instante en que el programa deja de acondicionar y empieza a secar.

    Devuelve None si la senal no alcanza para decidir; en ese caso quien llama
    se queda con la fecha que declara el informe."""
    for i, x in enumerate(R):
        if x["emcsp"] is None or x["emcsp"] > EMC_SECADO:
            continue
        tope = x["t"] + timedelta(hours=EMC_PERSIST)
        vals = [y["emcsp"] for y in R[i:] if y["t"] <= tope and y["emcsp"] is not None]
        if not vals:
            continue
        if max(vals) <= EMC_VUELTA:
            return x["t"]
    return None


def payload(cx, camara, ciclo):
    c = db.ciclo(cx, camara, ciclo)
    filas = db.serie(cx, camara, ciclo)
    if not c or not filas:
        return None

    R = [{"t": _dt(r["ts"]), "awm": r["awm"], "emc": r["emc"], "temp": r["temperatura"],
          "emcsp": r["conjunto_emc"], "tsp": r["temp_programada"]} for r in filas]
    R = [x for x in R if x["t"] and x["awm"] is not None and x["temp"] is not None
         and x["tsp"] is not None]
    if len(R) < 10:
        return None
    T0, T1 = R[0]["t"], R[-1]["t"]
    mins = lambda t: (t - T0).total_seconds() / 60.0

    ini_inf = _dt(c["inicio_informe"]) or T0
    fin_inf = _dt(c["fin_informe"]) or T1
    if not (T0 <= ini_inf <= T1):
        ini_inf = T0
    if fin_inf < T1:
        fin_inf = T1

    baldes = {}
    for x in R:
        baldes.setdefault(int(mins(x["t"]) // PASO), []).append(x)
    S = {"m": [], "awm": [], "emc": [], "emcsp": [], "temp": [], "tsp": [], "devmin": []}
    for b in sorted(baldes):
        g = baldes[b]
        f = g[0]
        S["m"].append(b * PASO)
        for k in ("awm", "emc", "emcsp", "temp", "tsp"):
            v = f[k]
            S[k].append(round(v, 1) if v is not None else None)
        S["devmin"].append(round(min(y["temp"] - y["tsp"] for y in g), 1))

    ini_sec = inicio_secado(R)
    if ini_sec is None or not (T0 <= ini_sec <= T1):
        ini_sec = ini_inf          # respaldo: la fecha que declara el informe

    awm_fin = R[-1]["awm"]
    corte = next((x for x in R if x["awm"] <= awm_fin + COLA_PTS), R[-1])
    if corte["t"] < ini_sec:
        corte = R[-1]
    fases = [
        {"id": "pre", "label": "Acondicionamiento", "desde": 0.0, "hasta": mins(ini_sec)},
        {"id": "sec", "label": "Secado efectivo", "desde": mins(ini_sec), "hasta": mins(corte["t"])},
        {"id": "cola", "label": "Cola de sobresecado", "desde": mins(corte["t"]), "hasta": mins(T1)},
    ]
    for f in fases:
        f["horas"] = round(max(0.0, f["hasta"] - f["desde"]) / 60.0, 1)

    ev, cur = [], None
    for x in R:
        d = x["temp"] - x["tsp"]
        if d < -5:
            cur = [x["t"], x["t"], d] if cur is None else [cur[0], x["t"], min(cur[2], d)]
        else:
            if cur and (cur[1] - cur[0]).total_seconds() >= 1200:
                ev.append(cur)
            cur = None
    if cur and (cur[1] - cur[0]).total_seconds() >= 1200:
        ev.append(cur)
    eventos = [{"desde": round(mins(a)), "hasta": round(mins(b)),
                "ini": a.strftime("%d-%m %H:%M"), "fin": b.strftime("%d-%m %H:%M"),
                "min_": round((b - a).total_seconds() / 60), "desv": round(d)} for a, b, d in ev]
    fuera = sum(1 for x in R if abs(x["temp"] - x["tsp"]) > 5)

    cortes = [50, 40, 30, 25, 20, 15, 12, 10, 9, 8.5, 8.0]
    tramos, prev, pv = [], T0, R[0]["awm"]
    for co in cortes:
        if co >= pv:
            continue
        hit = next((x for x in R if x["awm"] <= co), None)
        if not hit:
            continue
        fase = "cola" if hit["t"] >= corte["t"] else ("sec" if hit["t"] >= ini_sec else "pre")
        tramos.append({"de": pv, "a": co, "horas": round(_h(prev, hit["t"]), 1),
                       "acum": round(_h(T0, hit["t"]), 1), "fase": fase})
        prev, pv = hit["t"], co
    if _h(prev, T1) > 0.05:
        tramos.append({"de": pv, "a": round(awm_fin, 1), "horas": round(_h(prev, T1), 1),
                       "acum": round(_h(T0, T1), 1), "fase": "cola"})
    tramos = [t for t in tramos if t["horas"] > 0.05]

    gh_total = gh_cola = 0.0
    for i in range(len(R) - 1):
        dt = (R[i + 1]["t"] - R[i]["t"]).total_seconds() / 3600.0
        g = max(R[i]["temp"] - 20, 0) * dt
        gh_total += g
        if R[i]["t"] >= corte["t"]:
            gh_cola += g

    n = c["n_muestras"] or 0
    pct = lambda k: round(100.0 * (k or 0) / n, 2) if n else 0.0
    D = {
        "ciclo": ciclo, "camara": camara,
        "cliente": c["cliente"] or "Glover", "programa": c["programa"] or "",
        "especie": c["especie"] or "N/A",
        "ini_log": T0.isoformat(sep=" "), "fin_log": T1.isoformat(sep=" "),
        "ini_inf": ini_inf.isoformat(sep=" "), "fin_inf": fin_inf.isoformat(sep=" "),
        "ini_sec": ini_sec.isoformat(sep=" "), "sec_por_sensor": ini_sec != ini_inf,
        "t0": T0.strftime("%d-%m-%Y %H:%M"), "paso": PASO, "n_reg": len(R),
        "h_log": round(_h(T0, T1), 1), "h_inf": round(_h(ini_inf, fin_inf), 1),
        "h_total": round(_h(T0, fin_inf), 1),
        "h_pre": fases[0]["horas"], "h_sec": fases[1]["horas"], "h_cola": fases[2]["horas"],
        "h_enfr": round(max(0.0, _h(T1, fin_inf)), 1),
        "awm_fin": round(awm_fin, 1), "emc_fin": round(R[-1]["emc"] or 0, 1),
        "mc_medio": round(c["mc_medio"] or 0, 1), "mc_sd": round(c["mc_sd"] or 0, 2),
        "mc_min": c["mc_min"] or 0, "mc_max": c["mc_max"] or 0,
        "n_muestras": n, "n_bajas": c["n_bajas"] or 0, "n_altas": c["n_altas"] or 0,
        "n_rango": c["n_rango"] or 0,
        "pct_rango": pct(c["n_rango"]), "pct_bajas": pct(c["n_bajas"]), "pct_altas": pct(c["n_altas"]),
        "umbral": c["crit_umbral"], "objetivo": c["crit_objetivo"],
        "lo": c["crit_lo"], "hi": c["crit_hi"],
        "resultado": c["resultado"] or "-",
        "offset": round((c["mc_medio"] or awm_fin) - awm_fin, 1),
        "pct_fuera": round(100.0 * fuera / len(R), 1),
        "n_eventos": len(eventos), "desv_max": min([e["desv"] for e in eventos], default=0),
        "gh_total": round(gh_total), "gh_cola": round(gh_cola),
        "pct_gh_cola": round(100.0 * gh_cola / gh_total, 1) if gh_total else 0.0,
        "awm_cola_delta": round(corte["awm"] - awm_fin, 1),
        "fases": fases, "eventos": eventos, "tramos": tramos, "serie": S,
    }

    vals = [r["mc"] for r in db.muestras(cx, camara, ciclo)]
    RAW = {"ciclo": ciclo, "n": len(vals), "valores": vals,
           # el reparto en paquetes y la camara los resolvio la ingesta; la
           # pagina los usa tal cual en vez de volver a deducirlos
           "k": c["k_paquetes"], "grupo": c["grupo_camara"] or "p36",
           "media": round(st.mean(vals), 4) if vals else 0,
           "sd": round(st.stdev(vals), 4) if len(vals) > 1 else 0,
           "min": min(vals) if vals else 0, "max": max(vals) if vals else 0}
    return D, RAW


# ------------------------------------------------------------------ pagina
def _esqueleto(titulo, css_extra, cuerpo, scripts):
    return ('<!doctype html>\n<html lang="es" data-theme="light">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<style>html{color-scheme:light}body{margin:0}'
            'img{max-width:100%}[hidden]{display:none!important}</style>\n'
            + _frag("head.html").replace("<title>Ciclo de Secado 3367</title>",
                                         "<title>%s</title>" % titulo)
            + "\n" + "\n".join(css_extra) + "\n</head>\n<body>\n"
            + cuerpo + "\n" + "\n".join(scripts) + "\n</body>\n</html>\n")


def _panel_carga(lista, camara=None, ciclo=None):
    tr = []
    for c in lista:
        est = c["resultado"] or "&mdash;"
        cls = "ok" if est == "Aprobado" else ("no" if est == "Rechazado" else "")
        act = " class=\"actual\"" if (c["camara"] == camara and c["ciclo"] == ciclo) else ""
        tr.append(
            '<tr%s><td><a href="/?camara=%d&ciclo=%d">Cámara %d · Ciclo %d</a></td>'
            '<td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
            '<td><span class="est-pill %s">%s</span></td>'
            '<td><button class="del" data-c="%d" data-n="%d">Eliminar</button></td></tr>'
            % (act, c["camara"], c["ciclo"], c["camara"], c["ciclo"],
               "{:,}".format(c["n_proceso"]).replace(",", ".") if c["n_proceso"] else "—",
               c["n_muestra"] or "—", (c["fmt_proceso"] or "—").upper(),
               (c["inicio_log"] or c["inicio_informe"] or "—")[:16],
               cls, est, c["camara"], c["ciclo"]))
    if not tr:
        tr = ['<tr><td colspan="7" class="vacio">Todavía no hay ciclos cargados.</td></tr>']
    return (_frag("carga.html")
            .replace("__ABIERTO__", "" if lista else " open")
            .replace("__NCICLOS__", str(len(lista)))
            .replace("__URL_RED__", url_red())
            .replace("<!--__FILAS__-->", "".join(tr)))


def _selector(camara, ciclo, lista):
    op = "".join('<option value="%d/%d"%s>Cámara %d &middot; Ciclo %d</option>'
                 % (c["camara"], c["ciclo"],
                    " selected" if (c["camara"] == camara and c["ciclo"] == ciclo) else "",
                    c["camara"], c["ciclo"]) for c in lista)
    return ('<div class="ciclosel"><label for="selciclo">Ciclo en pantalla</label>'
            '<select id="selciclo">%s</select>'
            '<a href="/plano" target="_blank" rel="noopener">Plano de planta &nearr;</a>'
            '</div>' % op)


def render(cx, camara, ciclo, lista):
    """Pagina completa: cabecera + carga + tablero del ciclo."""
    p = payload(cx, camara, ciclo)
    if not p:
        return None
    D, RAW = p
    cab = (_frag("cabecera.html")
           .replace("__CICLO__", str(ciclo)).replace("__CAMARA__", str(camara))
           .replace("__PROGRAMA__", D["programa"] or "&mdash;"))
    cuerpo = (cab + _panel_carga(lista, camara, ciclo)
              + _selector(camara, ciclo, lista) + _frag("cuerpo.html"))
    return _esqueleto(
        "Ciclo %d · Cámara %d" % (ciclo, camara),
        [_frag("plan.css.html"), _frag("carga.css.html")],
        cuerpo,
        [_frag("proceso.js.html").replace("/*__DATA__*/", json.dumps(D, separators=(",", ":"))),
         _frag("muestras.js.html").replace("/*__MUESTRAS__*/",
                                           json.dumps(RAW, separators=(",", ":"))),
         _frag("carga.js.html")])


def render_vacio(lista, aviso=None):
    """Misma pagina, sin tablero: cuando no hay nada cargado o falta el PLC."""
    cab = (_frag("cabecera.html")
           .replace("__CICLO__", "—").replace("__CAMARA__", "—")
           .replace("__PROGRAMA__", "&mdash;"))
    hero = ('<div class="vacio-hero"><h2>%s</h2><p>%s</p></div>'
            % (aviso[0] if aviso else "Todavía no hay ciclos cargados",
               aviso[1] if aviso else
               "Abre el panel de arriba y arrastra el Excel de muestras y el programa de "
               "secado del ciclo. El sistema los revisa antes de guardar nada."))
    return _esqueleto("Sistema de Secado Glover",
                      [_frag("plan.css.html"), _frag("carga.css.html")],
                      cab + _panel_carga(lista) + hero,
                      [_frag("carga.js.html")])
