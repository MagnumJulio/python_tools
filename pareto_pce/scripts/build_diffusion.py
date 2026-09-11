#!/usr/bin/env python
# build_diffusion.py
# Le data/pce_indices_raw.csv (gerado por fetch_pce.py) e calcula difusao pros
# 4 agregados: Headline, Goods, Services, Goods ex cars.
#
# Definicao: Diffusao = share dos leaves com aumento de preco > 3% YoY. Pra
# Headline tambem calcula 6m anualizada: (idx[t]/idx[t-6])^2 - 1 > 3%.
#
# Uso:
#   cd pareto_pce
#   python scripts/build_diffusion.py

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN  = ROOT / "data" / "pce_indices_raw.csv"
OUT = ROOT / "data" / "pce_diffusion.csv"
LEAVES_OUT = ROOT / "data" / "leaves_detected.csv"

# Linhas que sao AGREGADOS ou SUB-AGREGADOS em U20404 — nao entram como leaves.
# Baseado em inspecao manual da hierarquia LineNumber do U20404. Se o count
# vier errado, ajusta esta lista.
SUBAGG_LINES = {
    # Goods aggregates
    1,   # Personal consumption expenditures (headline)
    2,   # Goods
    3,   # Durable goods
    4,   # Motor vehicles and parts
    5,   # New motor vehicles
    # Motor vehicles: cars sao contados no nivel de "linha de produto"
    # (6, 9, 13, 17, 21, 22) — nao nos deepest leaves. Portanto os deepest
    # (7,8,10,11,14,15,16,18,19) viram subagg tambem.
    7, 8,          # New domestic/foreign autos (rollup em 6)
    10, 11,        # New domestic/foreign light trucks (rollup em 9)
    12,            # Net purchases of used motor vehicles
    14, 15, 16,    # used autos deep details (rollup em 13)
    18, 19,        # used trucks deep details (rollup em 17)
    20,            # Motor vehicle parts and accessories (agg; 21+22 sao leaves)
    23,  # Furnishings and durable household equipment
    24,  # Furniture and furnishings
    29,  # Household appliances
    32,  # Glassware, tableware, and household utensils
    35,  # Tools and equipment for house and garden
    38,  # Recreational goods and vehicles
    39,  # Video, audio, photographic, and information processing equipment
    40,  # Video and audio equipment
    44,  # Recording media
    48,  # Information processing equipment
    53,  # Sports and recreational vehicles
    56,  # Pleasure boats, aircraft, and other recreational vehicles
    62,  # Other durable goods
    63,  # Jewelry and watches
    66,  # Therapeutic appliances and equipment
    72,  # Nondurable goods
    73,  # Food and beverages purchased for off-premises consumption
    74,  # Food and nonalcoholic beverages
    75,  # Food purchased for off-premises consumption
    76,  # Cereals and bakery products
    79,  # Meats and poultry
    85,  # Milk, dairy products, and eggs
    90,  # Fresh fruits and vegetables
    96,  # Nonalcoholic beverages
    99,  # Alcoholic beverages
    104, # Clothing and footwear
    105, # Garments
    109, # Other clothing materials and footwear
    113, # Gasoline and other energy goods
    114, # Motor vehicle fuels, lubricants, and fluids
    117, # Fuel oil and other fuels
    120, # Other nondurable goods
    121, # Pharmaceutical and other medical products
    122, # Pharmaceutical products
    126, # Recreational items
    131, # Household supplies
    137, # Personal care products
    142, # Magazines, newspapers, and stationery
    # Services aggregates
    150, # Services
    151, # Household consumption expenditures (for services)
    152, # Housing and utilities
    153, # Housing
    # Housing: colapsa sub-detalhes (155,157,158,161,162) e usa product-line
    # (154 Rental, 160 Imputed rental, 163 Farm, 164 Group) como leaves.
    155, 156, 157, 158, 159,  # Tenant-occupied detalhes / memo
    161, 162,                 # Owner-occupied mobile/stationary
    165, # Household utilities
    166, # Water supply and sanitation
    169, # Electricity and gas
    172, # Health care
    173, # Outpatient services
    179, # Other professional medical services
    182, # Hospital and nursing home services
    183, # Hospitals
    187, # Nursing homes
    190, # Transportation services
    191, # Motor vehicle services
    193, # Other motor vehicle services
    194, # Motor vehicle leasing
    199, # Public transportation
    200, # Ground transportation
    202, # Road transportation
    209, # Recreation services
    210, # Membership clubs, sports centers, parks, theaters, and museums
    # Admissions: colapsa 214,215,216 em 213 (product-line).
    214, 215, 216,           # Spectator amusements detalhes
    218, # Audio-video, photographic, and information processing equipment services
    223, # Video and audio streaming and rental
    226, # Gambling
    230, # Other recreational services
    234, # Food services and accommodations
    235, # Food services
    236, # Purchased meals and beverages
    237, # Meals and nonalcoholic beverages
    238, # Meals at schools
    241, # Other purchased meals
    246, # Food furnished to employees
    249, # Accommodations
    252, # Financial services and insurance
    253, # Financial services
    254, # Financial services furnished without payment
    258, # Financial service charges, fees, and commissions
    # Commissions: colapsa detalhes (262,263,265,266) em 260 Securities commissions.
    261, 262, 263, 264, 265, 266,
    270, # Insurance
    272, # Net household insurance
    # Excluir line 274 (adjustment "Less: Household insurance normal losses").
    274,
    275, # Net health insurance
    280, # Other services
    281, # Communication
    282, # Telecommunication services
    286, # Postal and delivery services
    290, # Education services
    291, # Higher education
    294, # Nursery, elementary, and secondary schools
    298, # Professional and other services
    300, # Accounting and other business services
    307, # Personal care and clothing services
    308, # Personal care services
    311, # Clothing and footwear services
    315, # Social services and religious activities
    317, # Social assistance
    320, # Individual and family services
    327, # Household maintenance
}

# Product-line leaves em Services que precisam ser REMOVIDOS de SUBAGG (aparecem
# em SUBAGG_LINES acima como agg pai, mas na verdade sao product-line leaves).
SERVICES_PRODUCT_LINE_LEAVES = {
    154, # Rental of tenant-occupied nonfarm housing (20)
    160, # Imputed rental of owner-occupied nonfarm housing (21)
    213, # Admissions to specified spectator amusements (product-line collapse)
    260, # Securities commissions (product-line collapse)
}
SUBAGG_LINES -= SERVICES_PRODUCT_LINE_LEAVES

# Linhas que NAO sao parte do escopo de difusao PCE core:
# - Expenditures abroad (146-149): ajustes cross-border
# - Foreign travel (334-341): ajustes
# - NPISHs (342-368): componente separado do PCE (nao household)
# - Derived aggregates (369-402): Control group, PCE ex food/energy, Market-based
OUT_OF_SCOPE_RANGES = [
    range(146, 150),  # 146-149
    range(334, 342),  # 334-341
    range(342, 369),  # 342-368
    range(369, 403),  # 369-402
]

# Leaves de "carros" (motor vehicles e parts) no nivel de linha de produto.
# Explicito por LineNumber pra evitar match fragil de string.
CAR_LINES = {
    6,   # New autos
    9,   # New light trucks
    13,  # Used autos
    17,  # Used light trucks
    21,  # Tires
    22,  # Accessories and parts
}


def load() -> pd.DataFrame:
    if not IN.exists():
        sys.exit(f"[FAIL] {IN} nao existe. Rode scripts/fetch_pce.py primeiro.")
    return pd.read_csv(IN, parse_dates=["date"])


def is_out_of_scope(ln: int) -> bool:
    return any(ln in r for r in OUT_OF_SCOPE_RANGES)


def identify_leaves(df: pd.DataFrame) -> pd.DataFrame:
    """Retorna DataFrame com (line_number, line_description, aggregate, is_car)
    contendo apenas leaves."""
    lines = (
        df[["line_number", "line_description"]]
        .drop_duplicates()
        .sort_values("line_number")
        .reset_index(drop=True)
    )
    # Boundary Goods vs Services via LineNumber
    svc_row = lines[lines.line_description == "Services"]
    goods_row = lines[lines.line_description == "Goods"]
    if svc_row.empty or goods_row.empty:
        sys.exit("[FAIL] Nao achei linhas 'Goods'/'Services' no U20404.")
    goods_start = int(goods_row.iloc[0].line_number)
    svc_start = int(svc_row.iloc[0].line_number)

    def classify(ln: int) -> str | None:
        if is_out_of_scope(ln):
            return None
        if ln in SUBAGG_LINES:
            return None
        if ln < goods_start:
            return None
        if ln < svc_start:
            return "Goods"
        return "Services"

    lines["aggregate"] = lines.line_number.astype(int).apply(classify)
    leaves = lines[lines["aggregate"].notna()].copy()

    leaves["is_car"] = leaves.line_number.astype(int).isin(CAR_LINES)
    # is_car so vale pra Goods
    leaves.loc[leaves["aggregate"] != "Goods", "is_car"] = False

    return leaves.reset_index(drop=True)


def compute_diffusion(df: pd.DataFrame, leaves: pd.DataFrame) -> pd.DataFrame:
    lm = df.merge(leaves[["line_number", "aggregate", "is_car"]], on="line_number")
    lm = lm.sort_values(["line_number", "date"])

    lm["yoy"] = lm.groupby("line_number")["value"].pct_change(12) * 100
    m6 = lm.groupby("line_number")["value"].pct_change(6)
    lm["m6_ann"] = ((1 + m6) ** 2 - 1) * 100

    def diffusion(rows: pd.DataFrame, col: str) -> pd.Series:
        return rows.groupby("date").apply(
            lambda g: (g[col] > 3).sum() / g[col].notna().sum() * 100
            if g[col].notna().any() else float("nan"),
            include_groups=False,
        )

    out_rows = []
    def add(rows, col, agg_name, metric):
        s = diffusion(rows, col).rename("value").reset_index()
        s["aggregate"] = agg_name
        s["metric"] = metric
        out_rows.append(s)

    add(lm, "yoy", "Headline", "diffusion_yoy_3pct")
    add(lm, "m6_ann", "Headline", "diffusion_6ma_ann_3pct")
    add(lm[lm["aggregate"] == "Goods"], "yoy", "Goods", "diffusion_yoy_3pct")
    add(lm[lm["aggregate"] == "Services"], "yoy", "Services", "diffusion_yoy_3pct")
    add(lm[(lm["aggregate"] == "Goods") & (~lm.is_car)], "yoy", "Goods_ex_cars",
        "diffusion_yoy_3pct")

    out = pd.concat(out_rows, ignore_index=True)[
        ["date", "aggregate", "metric", "value"]
    ]
    return out.sort_values(["metric", "aggregate", "date"]).reset_index(drop=True)


def main():
    df = load()
    leaves = identify_leaves(df)

    n_g = int((leaves["aggregate"] == "Goods").sum())
    n_s = int((leaves["aggregate"] == "Services").sum())
    n_car = int(leaves.is_car.sum())
    print(f"[leaves] Goods={n_g}, Services={n_s}, Total={n_g+n_s}, is_car={n_car}")
    print(f"[target] Goods=91, Services=109, Total=200, is_car=6")

    # Sempre grava leaves_detected pra auditoria
    leaves[["line_number", "line_description", "aggregate", "is_car"]].to_csv(
        LEAVES_OUT, index=False
    )
    print(f"[audit] leaves gravados em {LEAVES_OUT.relative_to(ROOT)}")

    if (n_g, n_s, n_car) != (91, 109, 6):
        print("\n[WARN] Contagem diverge do alvo. Confira leaves_detected.csv.")

    out = compute_diffusion(df, leaves)
    out.to_csv(OUT, index=False)
    print(f"\n[OK] {len(out)} rows -> {OUT.relative_to(ROOT)}")

    # Preview: ultimos 3 meses de cada metric
    print("\n[preview] Ultimos 3 meses:")
    for m in out.metric.unique():
        sub = out[out.metric == m].sort_values("date").tail(12)
        pv = sub.pivot(index="date", columns="aggregate", values="value")
        print(f"\n== {m} ==")
        print(pv.tail(3).round(2).to_string())


if __name__ == "__main__":
    main()
