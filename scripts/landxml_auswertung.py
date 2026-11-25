"""Auswertung des LandXML-Exports aus Civil 3D (ID 49).

Liest Achse, Gelaendeprofil, Gradiente und Querprofile aus data/ID49_Essen.xml
und erzeugt eine Stationstabelle, Kennzahlen und zwei Grafiken.
"""
from pathlib import Path
import math
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "data" / "ID49_Essen.xml"
RES = ROOT / "results"
IMG = ROOT / "images"
NS = {"l": "http://www.landxml.org/schema/LandXML-1.2"}
STEP = 20.0


def floats(text):
    return [float(v) for v in text.split()]


def read_landxml(path):
    root = ET.parse(path).getroot()
    surf = root.find(".//l:Surface", NS)
    sdef = surf.find("l:Definition", NS)
    surface = {
        "name": surf.get("name"),
        "points": len(sdef.findall(".//l:P", NS)),
        "faces": len(sdef.findall(".//l:F", NS)),
        "area2d": float(sdef.get("area2DSurf")),
        "area3d": float(sdef.get("area3DSurf")),
        "zmin": float(sdef.get("elevMin")),
        "zmax": float(sdef.get("elevMax")),
    }
    al = root.find(".//l:Alignment", NS)
    elements = []
    for el in al.find("l:CoordGeom", NS):
        tag = el.tag.split("}")[1]
        elements.append({"type": tag, "length": float(el.get("length")),
                         "radius": float(el.get("radius", "nan"))})
    start = floats(al.find("l:CoordGeom/*/l:Start", NS).text)
    end = floats(al.find("l:CoordGeom/*[last()]/l:End", NS).text)
    alignment = {"name": al.get("name"), "length": float(al.get("length")),
                 "elements": elements, "start_NE": start, "end_NE": end}
    prof = al.find("l:Profile", NS)
    g = floats(prof.find("l:ProfSurf/l:PntList2D", NS).text)
    ground = np.array(g).reshape(-1, 2)
    pvi = np.array([floats(p.text) for p in prof.findall("l:ProfAlign/l:PVI", NS)])
    sections = []
    for cs in al.findall("l:CrossSects/l:CrossSect", NS):
        pts = np.array(floats(cs.find(".//l:PntList2D", NS).text)).reshape(-1, 2)
        sections.append({"sta": float(cs.get("sta")), "name": cs.get("name"), "pts": pts})
    return surface, alignment, ground, pvi, sections


def main():
    RES.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)
    surface, al, ground, pvi, sections = read_landxml(XML)

    # Stationstabelle alle 20 m
    sta = np.arange(0, al["length"] + 1e-6, STEP)
    sta = np.append(sta, al["length"]) if sta[-1] < al["length"] - 0.01 else sta
    z_ground = np.interp(sta, ground[:, 0], ground[:, 1])
    z_design = np.interp(sta, pvi[:, 0], pvi[:, 1])
    diff = z_design - z_ground
    cs_by_sta = {round(s["sta"], 2): s for s in sections}
    rows = []
    for s, zg, zd, d in zip(sta, z_ground, z_design, diff):
        cs = cs_by_sta.get(round(s, 2))
        if cs is not None:
            p = cs["pts"]
            zl = np.interp(-20, p[:, 0], p[:, 1])
            zr = np.interp(20, p[:, 0], p[:, 1])
            q = (zr - zl) / 40 * 100
        else:
            zl = zr = q = np.nan
        rows.append({"Station": f"{int(s // 1000)}+{s % 1000:07.3f}", "Station_m": round(s, 2),
                     "Gelaende_m": round(zg, 3), "Gradiente_m": round(zd, 3),
                     "Differenz_m": round(d, 3),
                     "Art": "Auftrag" if d > 0.005 else ("Abtrag" if d < -0.005 else "-"),
                     "Gelaende_links_20m": round(zl, 3), "Gelaende_rechts_20m": round(zr, 3),
                     "Quergefaelle_%": round(q, 2)})
    table = pd.DataFrame(rows)
    table.to_csv(RES / "stationstabelle.csv", index=False, sep=";", decimal=",")

    grades = np.diff(pvi[:, 1]) / np.diff(pvi[:, 0]) * 100
    fine = np.linspace(0, al["length"], 2001)
    dz = np.interp(fine, pvi[:, 0], pvi[:, 1]) - np.interp(fine, ground[:, 0], ground[:, 1])
    fill_len = (dz > 0).sum() / len(dz) * al["length"]
    lines = [e for e in al["elements"] if e["type"] == "Line"]
    curves = [e for e in al["elements"] if e["type"] == "Curve"]
    kpi = [
        ("DGM Punkte", surface["points"]), ("DGM Dreiecke", surface["faces"]),
        ("DGM Flaeche 2D (m2)", round(surface["area2d"])),
        ("DGM Hoehe min / max (m)", f"{surface['zmin']:.2f} / {surface['zmax']:.2f}"),
        ("Achse Laenge (m)", round(al["length"], 2)),
        ("Achse Elemente", f"{len(lines)} Geraden, {len(curves)} Kreisbogen R = {curves[0]['radius']:.0f} m"),
        ("Gelaende Station 0 / Ende (m)", f"{z_ground[0]:.2f} / {z_ground[-1]:.2f}"),
        ("Gradiente PVI", ", ".join(f"{s:.0f}: {z:.2f}" for s, z in pvi)),
        ("Laengsneigung (%)", ", ".join(f"{g:.2f}" for g in grades)),
        ("Querprofile", len(sections)),
        ("max. Auftragshoehe Achse (m)", round(dz.max(), 2)),
        ("max. Abtragstiefe Achse (m)", round(-dz.min(), 2)),
        ("Laenge Auftrag / Abtrag (m)", f"{fill_len:.0f} / {al['length'] - fill_len:.0f}"),
    ]
    kp = pd.DataFrame(kpi, columns=["Kennzahl", "Wert"])
    kp.to_csv(RES / "kennzahlen.csv", index=False, sep=";")
    with pd.ExcelWriter(RES / "civil3d_achse_gradiente.xlsx") as xw:
        kp.to_excel(xw, sheet_name="Kennzahlen", index=False)
        table.to_excel(xw, sheet_name="Stationstabelle", index=False)

    # Grafik 1: Laengsschnitt aus LandXML
    fz_g = np.interp(fine, ground[:, 0], ground[:, 1])
    fz_d = np.interp(fine, pvi[:, 0], pvi[:, 1])
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.fill_between(fine, fz_g, fz_d, where=fz_d >= fz_g, color="#2e86c1", alpha=.25, label="Auftrag (fill)")
    ax.fill_between(fine, fz_g, fz_d, where=fz_d < fz_g, color="#c0392b", alpha=.25, label="Abtrag (cut)")
    ax.plot(ground[:, 0], ground[:, 1], color="#8b5a2b", lw=1.6, label="Gelaende DGM_Bestand")
    ax.plot(pvi[:, 0], pvi[:, 1], color="#1f3864", lw=2.2, label="Gradiente_1")
    ax.plot(pvi[:, 0], pvi[:, 1], "o", color="#1f3864")
    for (s0, z0), (s1, z1), g in zip(pvi[:-1], pvi[1:], grades):
        ax.text((s0 + s1) / 2, (z0 + z1) / 2 + 1.2, f"{g:.2f} %", ha="center", color="#1f3864", fontsize=10)
    ax.set_xlim(0, al["length"])
    ax.set_xlabel("Station (m)")
    ax.set_ylabel("Hoehe (m NHN)")
    ax.set_title("Achse_1 – Laengsschnitt aus LandXML (Civil 3D 2027)")
    ax.grid(alpha=.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(IMG / "05_Laengsschnitt_LandXML.png", dpi=150)
    plt.close(fig)

    # Grafik 2: sechs Querprofile
    pick = [20, 100, 200, 260, 380, 480]
    fig, axs = plt.subplots(2, 3, figsize=(12, 6), sharex=True)
    for a, s in zip(axs.flat, pick):
        cs = cs_by_sta[float(s)]
        p = cs["pts"]
        zd = np.interp(s, pvi[:, 0], pvi[:, 1])
        a.plot(p[:, 0], p[:, 1], color="#8b5a2b", lw=1.6)
        a.plot([0], [zd], "s", color="#1f3864")
        a.axvline(0, color="grey", lw=.8, ls="--")
        a.set_title(f"{cs['name']}  ·  Gradiente {zd:.2f} m", fontsize=10)
        a.grid(alpha=.3)
    for a in axs[1]:
        a.set_xlabel("Abstand zur Achse (m)")
    for a in axs[:, 0]:
        a.set_ylabel("Hoehe (m)")
    fig.suptitle("Querprofile Gelaende ±20 m (Auszug aus 25 Querprofilen)")
    fig.tight_layout()
    fig.savefig(IMG / "06_Querprofile_LandXML.png", dpi=150)
    plt.close(fig)
    print(kp.to_string(index=False))


if __name__ == "__main__":
    main()
