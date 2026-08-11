#!/usr/bin/env python3
# Por que: reconstroi agregados CPI-U a partir dos subitens (leaves) via
# Laspeyres Dez-anchor (BLS canonical). Analogo a reconstruct_ipca.R do
# pareto_ipca. NSA only (SA fica pro corp via opt_utils/X-13).
#
# Formula:
#   ratio_i(m)   = I_i(m) / I_i(Dec_{y-1})
#   ratio_agg(m) = Σ w_i(Dec_{y-1}) * ratio_i(m) / Σ w_i(Dec_{y-1})
#   I_agg(m)     = I_agg(Dec_{y-1}) * ratio_agg(m)
# Anchor inicial: 2019-12 = 100.0 (rebase arbitrario pra facilitar comparacao).
#
# Input:
#   data/cpi_cpius_subitem_hierarchy.csv (year, item_code, parent_code, is_leaf, cpi_u)
#   data/cpi_cpius_recon_subitem_raw.csv (date, item_code, cpi_u_nsa)
#   scripts/bls_maps/cpiu_table_1.csv    (category_code, item_code) — quais agregados servir
#
# Output:
#   data/cpi_cpius_recon_bottomup.csv    (date, category_code, item_code, index_nsa, var_mm)
import csv
from pathlib import Path
from datetime import date
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
H_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"
RAW_CSV = ROOT / "data" / "cpi_cpius_recon_subitem_raw.csv"
MAP_CSV = ROOT / "scripts" / "bls_maps" / "cpiu_table_1.csv"
CUSTOM_CSV = ROOT / "scripts" / "bls_maps" / "custom_aggregations.csv"
OUT_CSV = ROOT / "data" / "cpi_cpius_recon_bottomup.csv"

ANCHOR_YEAR = 2019
ANCHOR_MONTH = 12
ANCHOR_VALUE = 100.0

# Por que: leaves nao cobertos por nenhuma base cat (69 no total). Classificados
# como commodity ou service pra permitir computar core_goods / core_services.
# Baseado em nome do item + convencao BLS (SAC = commodities, SAS = services;
# food_home eh commodity, food_away eh service; energy_commodities eh commodity,
# energy_services eh service).
ORPHAN_COMMODITY_LEAVES = {
    # Household furnishings/products
    "SEHJ01", "SEHJ02", "SEHJ03",  # furniture
    "SEHK01", "SEHK02",             # appliances
    "SEHL01", "SEHL02", "SEHL03", "SEHL04",  # clocks/plants/dishes/cookware
    "SEHH01", "SEHH02", "SEHH03",  # floor/window/linens
    "SEHM01", "SEHM02",             # tools/outdoor eq
    "SEHN01", "SEHN02", "SEHN03",  # cleaning/paper/misc household
    # Personal care goods
    "SEGB01", "SEGB02", "SEGE",
    # Recreation goods
    "SERA01", "SERA03", "SERA05", "SERA06",  # TVs/video/audio/music
    "SERB01",                                  # pets and pet products
    "SERC01", "SERC02",                        # sports vehicles/equipment
    "SERD01",                                  # photo equipment
    "SERE01", "SERE02", "SERE03",              # toys/sewing/instruments
    "SERG01", "SERG02",                        # newspapers/books
    # Education/communication goods
    "SEEA",                                    # educational books
    "SEEE01", "SEEE02", "SEEE04",              # computers/software/phone hw
    # Transportation goods
    "SETC01", "SETC02",                        # tires/vehicle accessories
}

ORPHAN_SERVICE_LEAVES = {
    # Education services
    "SEEB01", "SEEB02", "SEEB03",
    # Communication services
    "SEED03", "SEED04", "SEEE03",
    # Postage/delivery
    "SEEC01", "SEEC02",
    # Recreation services
    "SERF01", "SERF02", "SERF03",
    "SERD02", "SERA02", "SERA04", "SERB02",
    # Personal services
    "SEGC01",
    # Other services
    "SEGD01", "SEGD02", "SEGD03", "SEGD04", "SEGD05",
    # Water/sewer/garbage (utility services, NOT energy)
    "SEHG01", "SEHG02",
    # Household services
    "SEHP01", "SEHP02", "SEHP03", "SEHP04",
    # Transportation services (orphans)
    "SETF01", "SETF03",  # motor vehicle fees, parking
    "SETA04",            # car and truck rental (current BLS code)
}

# Base cats classificadas como commodity (goods, excluindo food & energy)
CORE_GOODS_BASE_CATS = [
    "apparel", "new_vehicles", "used_cars_trucks",
    "medical_goods", "alcoholic_bev", "tobacco",
]

# Special Aggregates definidas via set-algebra sobre leaves de base cats + orphans.
# Fonte: BLS special aggregates (SA0E, SA0L1E, SASLE, SACL1E, etc.) reconstruidos
# a partir de leaves NSA.
# item_code eh o codigo publicado BLS (pra permitir audit vs CUUR).
SPECIAL_AGG_CODES = {
    "energy": "SA0E",
    "energy_commodities": "SACE",
    "energy_services": "SEHF",           # ja eh base cat, mas ok — resolvido via tree
    "core": "SA0L1E",
    "core_goods": "SACL1E",
    "core_services": "SASLE",
    "all_services": "SAS",
    "all_commodities": "SAC",
}


def load_hierarchy():
    """Retorna: kids_by_year[year][parent_code] = [child_codes]"""
    kids = defaultdict(lambda: defaultdict(list))
    all_codes_by_year = defaultdict(dict)  # year -> {code: {"weight":..., "is_leaf":..., "name":...}}
    for r in csv.DictReader(open(H_CSV, encoding="utf-8")):
        y = int(r["year"])
        code = r["item_code"]
        parent = r["parent_code"] or None
        if parent:
            kids[y][parent].append(code)
        all_codes_by_year[y][code] = {
            "weight": float(r["cpi_u"]),
            "is_leaf": r["is_leaf"] == "1",
            "name": r["item_name"],
        }
    return dict(kids), dict(all_codes_by_year)


def descendants_leaves(root, kids_map, codes_map):
    """Retorna set de codes leaves descendentes de root."""
    out = set()
    stk = [root]
    while stk:
        c = stk.pop()
        if codes_map.get(c, {}).get("is_leaf"):
            out.add(c)
        for k in kids_map.get(c, []):
            stk.append(k)
    return out


def load_subitem_indices():
    """Retorna: idx[code][date_tuple] = value (dict).
    date_tuple = (year, month)."""
    idx = defaultdict(dict)
    for r in csv.DictReader(open(RAW_CSV, encoding="utf-8")):
        d = r["date"]  # YYYY-MM-01
        y, m, _ = d.split("-")
        idx[r["item_code"]][(int(y), int(m))] = float(r["cpi_u_nsa"])
    return dict(idx)


def load_categories():
    """Retorna dict category_code -> item_code (BLS agg code)."""
    out = {}
    for r in csv.DictReader(open(MAP_CSV, encoding="utf-8")):
        out[r["category_code"]] = r["item_code"]
    return out


def all_leaves_in_year(codes_map):
    """Retorna set de todos os leaves na hierarquia."""
    return {c for c, info in codes_map.items() if info.get("is_leaf")}


def resolve_special_leaves(agg_name, cats_map, kids_map, codes_map):
    """Resolve leaves de special aggregates via set-algebra sobre base cats + orphans."""
    all_l = all_leaves_in_year(codes_map)

    def base_leaves(cat_name):
        ic = cats_map.get(cat_name)
        if ic is None or ic not in codes_map:
            return set()
        return descendants_leaves(ic, kids_map, codes_map)

    food_l = base_leaves("food")
    fuel_oil_l = base_leaves("fuel_oil")
    motor_fuel_l = base_leaves("motor_fuel")
    elec_l = base_leaves("electricity")
    gas_l = base_leaves("utility_gas")
    energy_comm_l = fuel_oil_l | motor_fuel_l
    energy_svc_l = elec_l | gas_l
    energy_l = energy_comm_l | energy_svc_l

    # Commodity leaves = food_home + all commodity base cats + energy_commodities + orphan commodities
    food_home_l = base_leaves("food_home")
    commodity_l = set(food_home_l) | energy_comm_l | (ORPHAN_COMMODITY_LEAVES & all_l)
    for gc in CORE_GOODS_BASE_CATS:
        commodity_l |= base_leaves(gc)

    # Services = all - commodities (inclui food_away, shelter, energy_services, etc.)
    services_l = all_l - commodity_l

    if agg_name == "energy":
        return energy_l
    if agg_name == "energy_commodities":
        return energy_comm_l
    if agg_name == "energy_services":
        return energy_svc_l
    if agg_name == "core":
        return all_l - food_l - energy_l
    if agg_name == "core_goods":
        return commodity_l - food_home_l - energy_comm_l
    if agg_name == "core_services":
        return services_l - energy_svc_l
    if agg_name == "all_services":
        return services_l
    if agg_name == "all_commodities":
        return commodity_l
    raise ValueError(f"Unknown special agg: {agg_name}")


def resolve_leaves_for(spec_name, spec_kind, cats_map, kids_map, codes_map,
                       custom_recipes=None):
    """Resolve leaves de qualquer agregacao.

    spec_kind = 'base' | 'special' | 'custom'
    - base:    usa descendants_leaves do item_code em cats_map
    - special: usa set-algebra pre-definida
    - custom:  aplica recipe (method=sum|exclude, base, excludes, includes)
    """
    if spec_kind == "base":
        ic = cats_map.get(spec_name)
        if ic is None or ic not in codes_map:
            return None
        return descendants_leaves(ic, kids_map, codes_map)
    if spec_kind == "special":
        return resolve_special_leaves(spec_name, cats_map, kids_map, codes_map)
    if spec_kind == "custom":
        recipe = custom_recipes[spec_name]
        method = recipe["method"]
        # base pode ser base cat OU special agg — resolve recursivamente
        if method == "exclude":
            base = recipe["base"]
            base_leaves = _resolve_by_name(base, cats_map, kids_map, codes_map)
            if base_leaves is None:
                return None
            excl = set()
            for x in recipe["excludes"]:
                xl = _resolve_by_name(x, cats_map, kids_map, codes_map)
                if xl is None:
                    print(f"    [WARN] {spec_name}: exclude ref '{x}' nao resolvido")
                    continue
                excl |= xl
            return base_leaves - excl
        if method == "sum":
            out = set()
            for x in recipe["includes"]:
                xl = _resolve_by_name(x, cats_map, kids_map, codes_map)
                if xl is None:
                    print(f"    [WARN] {spec_name}: include ref '{x}' nao resolvido")
                    continue
                out |= xl
            return out
        raise ValueError(f"Unknown method: {method}")
    raise ValueError(f"Unknown spec_kind: {spec_kind}")


def _resolve_by_name(name, cats_map, kids_map, codes_map):
    """Resolve nome (base cat ou special agg) pra leaves."""
    if name in SPECIAL_AGG_CODES:
        return resolve_special_leaves(name, cats_map, kids_map, codes_map)
    if name in cats_map and cats_map[name] in codes_map:
        return descendants_leaves(cats_map[name], kids_map, codes_map)
    return None


def annual_pivot_for(year, month):
    """Retorna (pivot_year, pivot_month) = Dec do ano anterior.
    Ex: (2020, 3) -> (2019, 12)."""
    return (year - 1, 12)


def weights_year_for(month_year):
    """Retorna qual ANO tem os pesos a usar. Pesos de Dec/2019 = weights do
    RI 2019 file (annual). Pesos de Dec/2020 = weights do RI 2020 file. Etc."""
    return month_year


def reconstruct_from_leaves(agg_name, leaves_resolver, kids_map_by_year,
                             codes_map_by_year, subitem_idx, verbose=False):
    """Reconstroi indice mensal via Laspeyres Dez-anchor a partir de um set de leaves.

    leaves_resolver(weights_year) -> set(leaf_codes) — permite que o conjunto de
    leaves mude ano a ano (RI pode adicionar/remover subitens).

    Retorna dict {(year, month): index_value} com anchor = ANCHOR_VALUE em
    (ANCHOR_YEAR, ANCHOR_MONTH).
    """
    all_months = set()
    for code, obs in subitem_idx.items():
        all_months.update(obs.keys())
    anchor = (ANCHOR_YEAR, ANCHOR_MONTH)
    months = sorted(m for m in all_months if m >= anchor)

    idx_agg = {anchor: ANCHOR_VALUE}

    for m in months:
        if m == anchor:
            continue
        y, mo = m
        p_year, _ = annual_pivot_for(y, mo)
        pivot = (p_year, 12)
        weights_yr = p_year
        if weights_yr not in codes_map_by_year:
            weights_yr = min(codes_map_by_year.keys())
        codes_map = codes_map_by_year[weights_yr]

        leaves = leaves_resolver(weights_yr)
        if not leaves:
            if verbose:
                print(f"    [WARN] {agg_name}: 0 leaves for weights_yr={weights_yr}")
            continue

        num = 0.0
        den = 0.0
        for lc in leaves:
            w = codes_map.get(lc, {}).get("weight")
            if w is None:
                continue
            i_pivot = subitem_idx.get(lc, {}).get(pivot)
            i_m = subitem_idx.get(lc, {}).get(m)
            if i_pivot is None or i_m is None or i_pivot == 0:
                continue
            num += w * (i_m / i_pivot)
            den += w
        if den == 0:
            continue
        ratio_agg = num / den

        if pivot in idx_agg:
            i_agg_pivot = idx_agg[pivot]
        else:
            i_agg_pivot = ANCHOR_VALUE
        idx_agg[m] = i_agg_pivot * ratio_agg

    return idx_agg


def load_custom_recipes():
    """Carrega custom_aggregations.csv em dict {code: {method, base, excludes, includes, label}}."""
    out = {}
    if not CUSTOM_CSV.exists():
        return out
    for r in csv.DictReader(open(CUSTOM_CSV, encoding="utf-8")):
        out[r["code"]] = {
            "method": r["method"],
            "base": r["base"] or None,
            "excludes": [x.strip() for x in r["excludes"].split(";") if x.strip()],
            "includes": [x.strip() for x in r["includes"].split(";") if x.strip()],
            "label": r["label"],
        }
    return out


def emit_index_rows(cat_code, item_code, idx_agg, out_rows):
    sorted_m = sorted(idx_agg.keys())
    for i, m in enumerate(sorted_m):
        v = idx_agg[m]
        if i == 0:
            var = None
        else:
            prev = idx_agg[sorted_m[i-1]]
            var = (v / prev - 1) * 100 if prev else None
        out_rows.append({
            "date": f"{m[0]:04d}-{m[1]:02d}-01",
            "category_code": cat_code,
            "item_code": item_code,
            "index_nsa": f"{v:.4f}",
            "var_mm": f"{var:.4f}" if var is not None else "",
        })


def main():
    print("[load] hierarchy + subitem indices + category map + custom recipes")
    kids_by_year, codes_by_year = load_hierarchy()
    subitem_idx = load_subitem_indices()
    cats = load_categories()
    customs = load_custom_recipes()

    print(f"[input] {len(kids_by_year)} anos hierarquia, {len(subitem_idx)} subitens fetched, "
          f"{len(cats)} base cats, {len(customs)} customs")

    out_rows = []

    # (1) Base cats: reconstroi a partir da tree
    print("\n[1] Base cats (Laspeyres bottom-up)")
    for cat_code, item_code in cats.items():
        any_year = next(iter(codes_by_year))
        if item_code not in codes_by_year[any_year]:
            # special aggregate — sera tratada no bloco 2
            continue

        def _lr(wy, _ic=item_code):
            codes_map = codes_by_year.get(wy, codes_by_year[min(codes_by_year)])
            kids_map = kids_by_year.get(wy, kids_by_year[min(kids_by_year)])
            return descendants_leaves(_ic, kids_map, codes_map)

        idx_agg = reconstruct_from_leaves(cat_code, _lr, kids_by_year, codes_by_year, subitem_idx)
        emit_index_rows(cat_code, item_code, idx_agg, out_rows)

    # (2) Special aggregates: set-algebra sobre base cat leaves + orphans
    print("\n[2] Special aggregates (set-algebra)")
    for spec_name, spec_code in SPECIAL_AGG_CODES.items():
        # Se ja foi tratado como base cat (energy_services=SEHF esta no tree), pula
        if spec_name in cats:
            any_year = next(iter(codes_by_year))
            if cats[spec_name] in codes_by_year[any_year]:
                continue

        def _lr(wy, _sn=spec_name):
            codes_map = codes_by_year.get(wy, codes_by_year[min(codes_by_year)])
            kids_map = kids_by_year.get(wy, kids_by_year[min(kids_by_year)])
            return resolve_special_leaves(_sn, cats, kids_map, codes_map)

        idx_agg = reconstruct_from_leaves(spec_name, _lr, kids_by_year, codes_by_year, subitem_idx)
        # weight preview no primeiro ano
        y0 = next(iter(codes_by_year))
        lv0 = resolve_special_leaves(spec_name, cats, kids_by_year[y0], codes_by_year[y0])
        w0 = sum(codes_by_year[y0][l]["weight"] for l in lv0 if l in codes_by_year[y0])
        print(f"  {spec_name:<20} ({spec_code}): {len(lv0)} leaves, w={w0:.3f}")
        emit_index_rows(spec_name, spec_code, idx_agg, out_rows)

    # (3) Customs: recipe-based
    print("\n[3] Customs (recipe-based)")
    for cust_code, recipe in customs.items():
        def _lr(wy, _cc=cust_code):
            codes_map = codes_by_year.get(wy, codes_by_year[min(codes_by_year)])
            kids_map = kids_by_year.get(wy, kids_by_year[min(kids_by_year)])
            return resolve_leaves_for(_cc, "custom", cats, kids_map, codes_map,
                                       custom_recipes=customs)

        # Verifica no primeiro ano se recipe resolve
        y0 = next(iter(codes_by_year))
        lv0 = resolve_leaves_for(cust_code, "custom", cats, kids_by_year[y0],
                                  codes_by_year[y0], custom_recipes=customs)
        if lv0 is None or not lv0:
            print(f"  [SKIP] {cust_code}: recipe nao resolveu")
            continue
        w0 = sum(codes_by_year[y0][l]["weight"] for l in lv0 if l in codes_by_year[y0])
        print(f"  {cust_code:<40} {len(lv0)} leaves, w={w0:.3f}")

        idx_agg = reconstruct_from_leaves(cust_code, _lr, kids_by_year, codes_by_year, subitem_idx)
        emit_index_rows(cust_code, "", idx_agg, out_rows)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "category_code", "item_code", "index_nsa", "var_mm"])
        w.writeheader()
        w.writerows(out_rows)
    n_cats = len({r["category_code"] for r in out_rows})
    print(f"\n[out] {OUT_CSV}: {len(out_rows)} linhas, {n_cats} categorias")


if __name__ == "__main__":
    main()
