# -*- coding: utf-8 -*-
"""
Creeaza cele doua grafice ale proiectului pe stratul cu judetele si le adauga la strat.

  Grafic 1 (Bar):     populatia expusa ponderata pe judete (SUM_pop_expusa)
  Grafic 2 (Scatter): hazard mediu (MEAN_..._HAZARD) fata de populatie (SUM_pop2020),
                      cu axa populatiei pe scara logaritmica

Optional, graficele se exporta si ca imagini SVG intr-un folder.

Parametrii Script Tool:
  0 = Strat judete         (Feature Layer, Required, Input)
  1 = Folder export SVG    (Folder, Optional, Input)
  2 = Strat cu grafice     (Feature Layer, Derived, Output, Dependency: parametrul 0)
"""
import os

import arcpy


def msg(text):
    print(text)
    arcpy.AddMessage(text)


def gaseste_camp(layer, *conditii):
    """Primul camp al carui nume (fara majuscule) contine toate textele date."""
    for f in arcpy.ListFields(layer):
        nume = f.name.lower()
        if all(c.lower() in nume for c in conditii):
            return f.name
    raise ValueError(f"Nu am gasit in strat un camp care sa contina: {', '.join(conditii)}")


def obiect_strat(param_index):
    """Intoarce stratul ca obiect arcpy.mp.Layer (necesar pentru addToLayer)."""
    valoare = arcpy.GetParameter(param_index)
    if isinstance(valoare, arcpy._mp.Layer):
        return valoare
    text = arcpy.GetParameterAsText(param_index)
    harta = arcpy.mp.ArcGISProject("CURRENT").activeMap
    for lyr in harta.listLayers():
        if lyr.isFeatureLayer and (lyr.longName == text or lyr.name == text
                                   or lyr.dataSource == text):
            return lyr
    raise ValueError(
        f"Stratul '{text}' nu este pe harta activa. "
        "Bifeaza Add To Display pe stratul de intrare sau deschide harta in care se afla."
    )


def seteaza(obiect, atribut, valoare):
    """Seteaza o proprietate optionala; daca versiunea ArcGIS nu o are, o ignora."""
    try:
        setattr(obiect, atribut, valoare)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        pass


def main():
    lyr = obiect_strat(0)
    folder_svg = arcpy.GetParameterAsText(1)

    camp_jud = gaseste_camp(lyr, "jud")
    camp_expusa = gaseste_camp(lyr, "sum", "expusa")
    camp_pop = gaseste_camp(lyr, "sum", "pop2020")
    try:
        camp_hazard = gaseste_camp(lyr, "mean", "hazard")
    except ValueError:
        camp_hazard = gaseste_camp(lyr, "mean")
    msg(f"Campuri folosite: {camp_jud}, {camp_expusa}, {camp_pop}, {camp_hazard}")

    # ---------------------------------------------------------- Grafic 1: bare
    bar = arcpy.charts.Bar(
        x=camp_jud,
        y=camp_expusa,
        aggregation="sum",
        title="Populația expusă ponderată cu hazardul, pe județe",
        dataSource=lyr,
    )
    bar.xAxis.title = "Județ"
    bar.yAxis.title = "Persoane expuse"
    bar.addToLayer(lyr)
    msg("Grafic 1 adaugat: populatia expusa pe judete (bare)")

    # ------------------------------------------------------ Grafic 2: dispersie
    scatter = arcpy.charts.Scatter(
        x=camp_hazard,
        y=camp_pop,
        title="Hazard seismic mediu și populație, pe județe",
        dataSource=lyr,
    )
    scatter.xAxis.title = "Hazard seismic mediu (0–1)"
    scatter.yAxis.title = "Populație (log)"
    seteaza(scatter.yAxis, "useLogarithmicScale", True)
    seteaza(scatter, "showTrendLine", False)
    scatter.addToLayer(lyr)
    msg("Grafic 2 adaugat: hazard mediu fata de populatie (dispersie)")

    # --------------------------------------------------------------- export SVG
    if folder_svg:
        for grafic, nume in [(bar, "grafic_populatie_expusa.svg"),
                             (scatter, "grafic_hazard_populatie.svg")]:
            cale = os.path.join(folder_svg, nume)
            grafic.exportToSVG(cale, width=1200, height=600)
            msg(f"Exportat: {cale}")

    arcpy.SetParameter(2, lyr)


if __name__ == "__main__":
    main()
