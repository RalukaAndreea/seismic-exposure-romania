# -*- coding: utf-8 -*-
"""
Hazard seismic si expunere la nivel de UAT (proiect BDS, ArcGIS Pro).

Pentru fiecare UAT se foloseste un punct interior al poligonului
(echivalentul Feature To Point cu optiunea Inside) si se calculeaza:

  R (km)     = sqrt(distanta_orizontala^2 + adancime^2)   distanta hipocentrala
  scor       = Mw - K * log10(R)                          proxy simplificat de efect
  HAZARD     = maximul scorului peste toate cutremurele
  EXPUNERE   = HAZARD_N * POP_N                           ambele normalizate 0-1
  POP_EXPUSA = pop2020 * HAZARD_N                         populatie ponderata cu hazardul

Populatia se normalizeaza pe scara logaritmica, altfel Bucurestiul
(peste 2 milioane de locuitori) ar aduce toate celelalte UAT-uri aproape de 0.

Atentie: e un indicator didactic, nu un model real de atenuare seismica.
Datele trebuie sa fie in Stereo 70 (unitati in metri).

Directivitate (optional): cutremurele intermediare din Vrancea nu radiaza
uniform; efectele se propaga alungit pe axa NE-SV. Cu factor_directivitate > 1,
pentru aceste cutremure componenta distantei de-a lungul axei se imparte la
factor, iar cea perpendiculara ramane neschimbata:
  d_ef = sqrt((u / factor)^2 + v^2),  u = de-a lungul axei, v = perpendicular
Factorul 1 inseamna fara directivitate (cercuri). Valorile sunt alese aproximativ,
pentru un test de sensibilitate, nu dintr-o calibrare.

Scenarii: cu un sufix (de exemplu "_1977") campurile se scriu separat
(HAZARD_1977, EXPUNERE_1977 ...), fara sa suprascrie rezultatele principale.

Rulare:
  - ca Script Tool: 0 = UAT, 1 = cutremure, 2 = K (optional), 3 = sufix (optional),
    4 = UAT actualizat (iesire derivata, pentru legarea in ModelBuilder),
    5 = factor directivitate (optional, implicit 1), 6 = azimut axa (optional, implicit 45)
  - din Python window: exec(...) cu hazard_seismic_final.py ruleaza calculul principal cu valorile implicite;
    dupa aceea functia se poate apela direct, de exemplu:
        calculeaza_hazard("UAT_Stereo70", "Cutremur_1977", sufix="_1977")
        calculeaza_hazard("UAT_Stereo70", "Cutremur_1977", sufix="_1977D",
                          factor_directivitate=2)
"""
import math
from collections import Counter

import arcpy
import numpy as np

MAG_FIELD = "Mw"               # magnitudinea moment
DEPTH_FIELD = "Depth"          # adancimea, in km
YEAR_FIELD = "Year_UTC"
SOURCE_FIELD = "Source_name"   # zona sursa (ex. Vrancea intermediate)
POP_FIELD = "pop2020"
DEFAULT_DEPTH_KM = 10.0        # folosita daca adancimea lipseste
# Directivitatea se aplica doar cutremurelor intermediare din Vrancea.
DIRECTIV_SURSA = "Vrancea"     # text cautat in Source_name
DIRECTIV_ADANCIME_MIN = 60.0   # km


def msg(text):
    """Afiseaza mesajul si in Python Window, si in mesajele Script Tool-ului."""
    print(text)
    arcpy.AddMessage(text)


def norm(value, lo, hi):
    return (value - lo) / (hi - lo) if hi > lo else 0.0


def verifica_proiectia(fc):
    sr = arcpy.Describe(fc).spatialReference
    if sr.type != "Projected" or sr.linearUnitName != "Meter":
        raise ValueError(
            f"{fc} nu este intr-un sistem proiectat in metri ({sr.name}). "
            "Proiecteaza datele in Stereo 70 inainte de rulare."
        )


def calculeaza_hazard(uat_fc="UAT_Stereo70", eq_fc="Cutremure_M4", K=1.5, sufix="",
                      factor_directivitate=1.0, azimut=45.0):
    """Calculeaza hazardul si expunerea pe UAT si scrie rezultatele in uat_fc.

    Cutremurele: daca eq_fc e un strat cu selectie, se folosesc doar cele selectate.
    UAT-urile: se proceseaza intotdeauna toate, chiar daca stratul are o selectie.
    """
    # Toate UAT-urile, indiferent de selectia de pe strat (altfel normalizarea
    # s-ar face doar pe o parte din tara).
    uat_data = arcpy.Describe(uat_fc).catalogPath

    for fc in (uat_data, eq_fc):
        verifica_proiectia(fc)

    # -------------------------------------------------- citirea cutremurelor
    xs, ys, mags, depths, years, sources = [], [], [], [], [], []
    with arcpy.da.SearchCursor(
        eq_fc,
        ["SHAPE@X", "SHAPE@Y", MAG_FIELD, DEPTH_FIELD, YEAR_FIELD, SOURCE_FIELD],
    ) as cursor:
        for x, y, mag, depth, year, source in cursor:
            if x is None or mag is None:
                continue
            xs.append(x)
            ys.append(y)
            mags.append(mag)
            depths.append(depth if depth is not None else DEFAULT_DEPTH_KM)
            years.append(year if year is not None else 0)
            sources.append(source if source else "Necunoscuta")

    if not xs:
        raise ValueError("Nu exista cutremure valide in stratul de intrare.")

    xs, ys = np.array(xs), np.array(ys)
    mags, depths = np.array(mags, dtype=float), np.array(depths, dtype=float)
    msg(f"Cutremure citite: {len(xs)}")
    if len(xs) == 1:
        msg(f"  Scenariu cu un singur cutremur: Mw {mags[0]}, "
            f"adancime {depths[0]} km, anul {years[0]}")

    # ------------------------------------------------------- directivitate
    directiv = np.array([
        DIRECTIV_SURSA.lower() in src.lower() and d >= DIRECTIV_ADANCIME_MIN
        for src, d in zip(sources, depths)
    ])
    aplica_directiv = factor_directivitate > 1.0 and directiv.any()
    if aplica_directiv:
        sin_a = math.sin(math.radians(azimut))
        cos_a = math.cos(math.radians(azimut))
        msg(f"  Directivitate: factor {factor_directivitate}, axa la {azimut} grade, "
            f"aplicata pe {int(directiv.sum())} cutremure intermediare din Vrancea")
    else:
        msg("  Fara directivitate (distanta izotropa)")

    # --------------------------------------------- hazardul pe fiecare UAT
    results = {}  # OID -> (hazard, mw, an, distanta_km, sursa, log_pop, pop)
    with arcpy.da.SearchCursor(uat_data, ["OID@", "SHAPE@", POP_FIELD]) as cursor:
        for oid, geom, pop in cursor:
            if geom is None:
                continue
            pt = geom.labelPoint if geom.type == "polygon" else geom.firstPoint

            dx_km = (xs - pt.X) / 1000.0
            dy_km = (ys - pt.Y) / 1000.0
            h2 = dx_km ** 2 + dy_km ** 2           # distanta orizontala la patrat
            if aplica_directiv:
                u = dx_km * sin_a + dy_km * cos_a  # de-a lungul axei
                v = dx_km * cos_a - dy_km * sin_a  # perpendicular pe axa
                h2 = np.where(directiv, (u / factor_directivitate) ** 2 + v ** 2, h2)
            r_km = np.sqrt(h2 + depths ** 2)
            r_km = np.maximum(r_km, 1.0)  # evita log10(0)

            scores = mags - K * np.log10(r_km)
            i = int(np.argmax(scores))

            pop = pop or 0
            log_pop = math.log10(pop + 1) if pop else 0.0
            results[oid] = (
                float(scores[i]), float(mags[i]), int(years[i]),
                float(r_km[i]), sources[i], log_pop, pop,
            )

    msg(f"UAT-uri procesate: {len(results)}")

    # -------------------------------------------------------- normalizare
    h_min = min(v[0] for v in results.values())
    h_max = max(v[0] for v in results.values())
    p_min = min(v[5] for v in results.values())
    p_max = max(v[5] for v in results.values())

    # -------------------------------------------------- campurile de iesire
    new_fields = [
        ("HAZARD", "DOUBLE"),
        ("EQ_MW", "DOUBLE"),       # magnitudinea cutremurului care da maximul
        ("EQ_AN", "LONG"),         # anul acelui cutremur
        ("DIST_KM", "DOUBLE"),     # distanta hipocentrala pana la el
        ("EQ_SURSA", "TEXT"),      # zona sursa a acelui cutremur
        ("HAZARD_N", "DOUBLE"),
        ("POP_N", "DOUBLE"),
        ("EXPUNERE", "DOUBLE"),
        ("POP_EXPUSA", "DOUBLE"),  # pop2020 * HAZARD_N
    ]
    new_fields = [(name + sufix, ftype) for name, ftype in new_fields]

    existing = {f.name.upper() for f in arcpy.ListFields(uat_data)}
    for name, ftype in new_fields:
        if name.upper() not in existing:
            if ftype == "TEXT":
                arcpy.management.AddField(uat_data, name, ftype, field_length=100)
            else:
                arcpy.management.AddField(uat_data, name, ftype)

    # ------------------------------------------------------------- scriere
    field_names = ["OID@"] + [name for name, _ in new_fields]
    with arcpy.da.UpdateCursor(uat_data, field_names) as cursor:
        for row in cursor:
            oid = row[0]
            if oid not in results:
                continue
            hazard, mw, an, dist, sursa, log_pop, pop = results[oid]
            h_n = norm(hazard, h_min, h_max)
            p_n = norm(log_pop, p_min, p_max)
            pop_expusa = pop * h_n
            cursor.updateRow(
                [oid, hazard, mw, an, dist, sursa, h_n, p_n, h_n * p_n, pop_expusa]
            )

    msg(f"Hazard intre {h_min:.2f} si {h_max:.2f} (K = {K}).")
    msg("Campuri scrise: " + ", ".join(n for n, _ in new_fields))

    # --------------------------------- cate UAT-uri domina fiecare sursa
    if len(xs) > 1:
        for sursa, nr in Counter(v[4] for v in results.values()).most_common():
            msg(f"  {sursa}: {nr} UAT-uri")


# ---------------------------------------------------------------- rulare
if __name__ == "__main__":
    uat_param = arcpy.GetParameterAsText(0) or "UAT_Stereo70"

    def param_numeric(index, implicit):
        try:
            if arcpy.GetParameterAsText(index):
                return float(arcpy.GetParameter(index))
        except (IndexError, RuntimeError, TypeError, ValueError):
            pass
        return implicit

    calculeaza_hazard(
        uat_fc=uat_param,
        eq_fc=arcpy.GetParameterAsText(1) or "Cutremure_M4",
        K=param_numeric(2, 1.5),
        sufix=arcpy.GetParameterAsText(3) or "",
        factor_directivitate=param_numeric(5, 1.0),
        azimut=param_numeric(6, 45.0),
    )
    # Parametrul 4 (iesire derivata): acelasi strat UAT, acum cu campurile noi.
    # In ModelBuilder, instrumentele urmatoare se leaga de el, ca sa ruleze dupa script.
    if arcpy.GetParameterAsText(0):
        arcpy.SetParameterAsText(4, uat_param)
