#!/usr/bin/env python3
# Por que: parse arquivos historicos BLS Table 1 Relative Importance (2000-2025)
# e gera data/cpi_cpius_pesos_annual.csv com RI CPI-U para as 37 categorias.
# Fontes: bls.gov/cpi/tables/relative-importance/, formatos txt (2000-2019) + xlsx (2020-2025).
import re
import csv
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "relative_importance"
OUT = ROOT / "data" / "cpi_cpius_pesos_annual.csv"

# (category_code, label_canonico, [labels_fallback]) por ordem de preferencia.
# Fallbacks cobrem drift historico (ex.: "Owners' equivalent rent of residences" vs
# "...of primary residence"; "Utility (piped) gas" vs "Utility natural gas").
CATS = [
    ("all_items", "All items", []),
    ("food", "Food", []),
    ("food_home", "Food at home", []),
    ("food_cereals_bakery", "Cereals and bakery products", []),
    ("food_meats", "Meats, poultry, fish, and eggs", []),
    ("food_dairy", "Dairy and related products", []),
    ("food_fruits_veg", "Fruits and vegetables", []),
    ("food_nonalc_bev", "Nonalcoholic beverages and beverage materials", []),
    ("food_other_home", "Other food at home", []),
    ("food_away", "Food away from home", []),
    ("energy", "Energy", []),
    ("energy_commodities", "Energy commodities", []),
    ("fuel_oil", "Fuel oil", []),
    ("motor_fuel", "Motor fuel", []),
    ("gasoline", "Gasoline (all types)", []),
    ("energy_services", "Energy services", ["Gas (piped) and electricity"]),
    ("electricity", "Electricity", []),
    ("utility_gas", "Utility (piped) gas service", ["Utility natural gas service"]),
    ("core", "All items less food and energy", []),
    ("core_goods", "Commodities less food and energy commodities", []),
    ("apparel", "Apparel", []),
    ("new_vehicles", "New vehicles", []),
    ("used_cars_trucks", "Used cars and trucks", []),
    ("medical_goods", "Medical care commodities", []),
    ("alcoholic_bev", "Alcoholic beverages", []),
    ("tobacco", "Tobacco and smoking products", []),
    ("core_services", "Services less energy services", []),
    ("shelter", "Shelter", []),
    ("rent", "Rent of primary residence", []),
    ("oer", "Owners' equivalent rent of residences",
        ["Owners' equivalent rent of primary residence"]),
    ("lodging_away", "Lodging away from home", []),
    ("medical_services", "Medical care services", []),
    ("physicians_services", "Physicians' services", []),
    ("hospital_services", "Hospital services", ["Hospital and related services"]),
    ("transportation_services", "Transportation services", []),
    ("motor_vehicle_maint", "Motor vehicle maintenance and repair", []),
    ("motor_vehicle_insur", "Motor vehicle insurance", []),
    ("public_transportation", "Public transportation", []),
    ("airline_fares", "Airline fares", ["Airline fare"]),
]

# Cats derivaveis por soma quando labels historicos nao existem.
DERIVED = {
    "energy_services": ["electricity", "utility_gas"],
}


def _to_float(tok):
    # BLS usa `.851` sem zero a esquerda; `100.000` como 100; `-` como NA.
    tok = tok.strip()
    if not tok or tok == "-":
        return None
    try:
        return float(tok)
    except ValueError:
        return None


# -------- txt parser (2000-2019) --------
# Layout fixed-width: `<spaces><label>...<dots>...<cpi_u>   <cpi_w>`
# Extrai (indent, label, cpi_u, cpi_w).
RE_TXT_ROW = re.compile(
    r"^(\s+)([A-Za-z][A-Za-z0-9,'()\-/ &.]+?)\s*\.{2,}\s*([\d.\-]+)\s+([\d.\-]+)\s*$"
)


def parse_txt(path):
    """Retorna dict {label_stripped: cpi_u_float}. Trata quebras (linha 2 apenas com cauda do label + valor)."""
    rows = {}
    prev_label = None
    with open(path, encoding="latin-1") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        line = line.rstrip("\n")
        m = RE_TXT_ROW.match(line)
        if m:
            _indent, label, cu, _cw = m.groups()
            label = label.strip()
            # Trata wrap: quando linha anterior era rotulo puro sem valor (label wrap).
            if prev_label and label[0].islower():
                label = prev_label + " " + label
            if label not in rows:  # primeira ocorrencia vence (respeita ordem hierarquica)
                v = _to_float(cu)
                if v is not None:
                    rows[label] = v
            prev_label = None
        else:
            # detecta label wrap (linha com texto mas sem dots/valor)
            stripped = line.strip()
            if stripped and "..." not in line and not any(c.isdigit() for c in stripped):
                prev_label = stripped
            else:
                prev_label = None
    return rows


# -------- xlsx parser (2020-2025) --------
def parse_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Table 1"]
    rows = {}
    for r in ws.iter_rows(min_row=1, values_only=True):
        if not r or r[0] is None or not isinstance(r[0], int):
            continue
        indent = r[0]
        label = r[1]
        if not label:
            continue
        label = str(label).strip()
        # coluna C (index 2) = CPI-U
        cu = r[2]
        if isinstance(cu, (int, float)) and label not in rows:
            rows[label] = float(cu)
    return rows


def resolve_cats(rows_by_label, year):
    """Aplica CATS + fallbacks + DERIVED sobre um dict label->value."""
    out = {}
    for code, canonical, fallbacks in CATS:
        val = rows_by_label.get(canonical)
        if val is None:
            for fb in fallbacks:
                if fb in rows_by_label:
                    val = rows_by_label[fb]
                    break
        if val is not None:
            out[code] = val

    # deriva por soma quando nao achou
    for code, parts in DERIVED.items():
        if code in out:
            continue
        if all(p in out for p in parts):
            out[code] = round(sum(out[p] for p in parts), 3)
    return out


def main():
    files = []
    # 2000-2009 archive: usa apenas <year>.txt (nao os `old-weights-*.txt`)
    for p in sorted((RAW / "ri-archive-2000-2009" / "2000-2009_RI_archive").glob("[0-9]*.txt")):
        if "old-weights" in p.name:
            continue
        files.append((int(p.stem), p, "txt"))
    for p in sorted((RAW / "ri-archive-2010-2019" / "2010-2019_RI_archive").glob("[0-9]*.txt")):
        if "old-weights" in p.name:
            continue
        files.append((int(p.stem), p, "txt"))
    for p in sorted(RAW.glob("[0-9]*.xlsx")):
        files.append((int(p.stem), p, "xlsx"))

    print(f"[parse_ri] {len(files)} arquivos encontrados")

    annual = {}   # year -> {code: value}
    missing = {}  # year -> [cats_faltantes]
    for year, path, kind in files:
        rows = parse_txt(path) if kind == "txt" else parse_xlsx(path)
        resolved = resolve_cats(rows, year)
        annual[year] = resolved
        miss = [c for c, _, _ in CATS if c not in resolved]
        if miss:
            missing[year] = miss
        print(f"  {year} ({kind}): {len(resolved)}/37 cats, all_items={resolved.get('all_items','?')}")

    # Sanity checks
    print("\n[sanity] Validando hierarquia food+energy+core = 100.000 por ano:")
    for year in sorted(annual):
        d = annual[year]
        if all(k in d for k in ("food", "energy", "core")):
            s = d["food"] + d["energy"] + d["core"]
            flag = "OK" if abs(s - 100) < 0.5 else "WARN"
            print(f"  {year}: food={d['food']:.3f} + energy={d['energy']:.3f} + core={d['core']:.3f} = {s:.3f} [{flag}]")
        else:
            print(f"  {year}: FALTA algum dos 3 top-level")

    if missing:
        print("\n[missing] categorias nao localizadas por ano:")
        for y, ms in missing.items():
            print(f"  {y}: {ms}")

    # Grava CSV long
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "category_code", "relative_importance"])
        for year in sorted(annual):
            for code, _, _ in CATS:
                if code in annual[year]:
                    w.writerow([year, code, annual[year][code]])
    total_rows = sum(len(v) for v in annual.values())
    print(f"\n[out] {OUT} ({total_rows} linhas, {len(annual)} anos)")


if __name__ == "__main__":
    main()
