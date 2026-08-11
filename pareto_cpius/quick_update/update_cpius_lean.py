#!/usr/bin/env python3
"""update_cpius_lean.py — atualizacao seletiva CPI-U por bls_code direto no SQL corp.

Self-contained: nao depende do pipeline completo em `scripts/` ou dos CSVs em
`data/`. Puxa idx da BLS API v2 em batch, calcula Weight pelo ajuste implicito
BLS usando a base RI historica hardcoded no proprio script, e escreve direto
em OPT_Macro_Series_2 / OPT_Macro_Series_Data_2 (via opt_utils.database).

Uso:
    python update_cpius_lean.py --cats core_goods,oer
    python update_cpius_lean.py --codes "CPIUS:core_goods,CPIUS:oer,CPIUS:core"
    python update_cpius_lean.py --cats gasoline --api-key XXX
    python update_cpius_lean.py --cats core_goods --simulate  # local: sem SQL

Regras:
    - 1 bls_code -> 3 series no SQL: idx NSA + idx SA + Weight.
      Todas as 41 base cats tem RI historico (2000-2025) parseado dos arquivos
      Table 6 anuais. Pra `medical_care` (SAM), 2000-2002 nao lista SAM direto
      e a RI eh derivada como SAM1+SAM2 no parser.
    - Fetch idx: 1 POST batchado pra ate 50 series (com --api-key) ou 25 sem.
      Ate 20 anos por request com key, 10 sem. Splitta janelas se precisar.
    - Weight: ajuste implicito BLS `w(m) = w(Dez_prev) x I(m) / I(Dez_prev)`,
      renormalizado pros 3 top-1 (food+energy+core) somarem 100. all_items
      forcado 100.0 constante.
    - Upsert incremental: cada re-run so DELETE+INSERT os ultimos
      INCREMENTAL_MONTHS (=24) por serie no SQL corp. Primeira vez pra uma
      serie faz seed full. Nao preserva vintages (release_date=today em tudo).
    - Base cats (41 do release BLS Table 1) + customs (8 agregacoes Laspeyres
      Dez-anchor, espelhando build_custom_aggregations.R). Deps das customs
      (base/excludes/includes) sao automaticamente adicionadas ao fetch mas
      NAO sao inseridas no SQL se nao pedidas explicitamente.

ATENCAO — atualizar 1x/ano:
    RI_BASE_DATE e RI_HISTORICAL[novo_ano] precisam ser atualizados quando BLS
    publicar novo release de Table 6 (Relative Importance), tipicamente ~Fev
    de cada ano. Se rodar com RI_BASE_DATE > 12 meses atrasada em relacao ao
    ultimo mes de idx retornado pela BLS, o script printa [WARN] no inicio.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from typing import Iterable

import pandas as pd
import requests


# Wall-clock relativa ao start pra prefixar todos os logs.
_T0 = time.monotonic()


def log(msg: str) -> None:
    """Print com [t=Xs] pra dar noção de progresso a olho nu."""
    dt = time.monotonic() - _T0
    print(f"[t={dt:6.1f}s] {msg}", flush=True)


# ============================================================================
# METADATA HARDCODED — ver docstring pra quando atualizar cada bloco
# ============================================================================

# Item codes BLS Table 1. Series IDs formados como CUUR0000<item> (NSA) e
# CUSR0000<item> (SA). Estavel: proxima revisao ~POF 2028. Fonte:
# `scripts/bls_maps/cpiu_table_1.csv` no pipeline completo.
ITEM_CODES = {
    "all_items": "SA0",
    "food": "SAF1",
    "food_home": "SAF11",
    "food_cereals_bakery": "SAF111",
    "food_meats": "SAF112",
    "food_dairy": "SAF113",
    "food_fruits_veg": "SAF114",
    "food_nonalc_bev": "SAF115",
    "food_other_home": "SAF116",
    "food_away": "SEFV",
    "energy": "SA0E",
    "energy_commodities": "SACE",
    "fuel_oil": "SEHE",
    "motor_fuel": "SETB",
    "gasoline": "SETB01",
    "energy_services": "SEHF",
    "electricity": "SEHF01",
    "utility_gas": "SEHF02",
    "core": "SA0L1E",
    "core_goods": "SACL1E",
    "apparel": "SAA",
    "new_vehicles": "SETA01",
    "used_cars_trucks": "SETA02",
    "car_truck_rental": "SETA03",
    "medical_care": "SAM",
    "medical_goods": "SAM1",
    "alcoholic_bev": "SEAF",
    "tobacco": "SEGA",
    "core_services": "SASLE",
    "shelter": "SAH1",
    "rent": "SEHA",
    "oer": "SEHC",
    "lodging_away": "SEHB",
    "medical_services": "SAM2",
    "physicians_services": "SEMC01",
    "hospital_services": "SEMD01",
    "transportation_services": "SAS4",
    "motor_vehicle_maint": "SETD",
    "motor_vehicle_insur": "SETE",
    "public_transportation": "SETG",
    "airline_fares": "SETG01",
}

# Labels de series_name no SQL. Espelha
# `script_itau/load_cpius_to_sql.py::CATEGORY_LABELS` (sync 2026-07-21). Nao
# muda com release BLS — decisao de nomenclatura interna.
CATEGORY_LABELS = {
    "all_items":               "CPI-U: All Items",
    "food":                    "CPI-U: Food",
    "food_home":               "CPI-U: Food at Home",
    "food_cereals_bakery":     "CPI-U: Cereals and Bakery Products",
    "food_meats":              "CPI-U: Meats, Poultry, Fish, and Eggs",
    "food_dairy":              "CPI-U: Dairy and Related Products",
    "food_fruits_veg":         "CPI-U: Fruits and Vegetables",
    "food_nonalc_bev":         "CPI-U: Nonalcoholic Beverages and Beverage Materials",
    "food_other_home":         "CPI-U: Other Food at Home",
    "food_away":               "CPI-U: Food Away from Home",
    "energy":                  "CPI-U: Energy",
    "energy_commodities":      "CPI-U: Energy Commodities",
    "fuel_oil":                "CPI-U: Fuel Oil",
    "motor_fuel":              "CPI-U: Motor Fuel",
    "gasoline":                "CPI-U: Gasoline (all types)",
    "energy_services":         "CPI-U: Energy Services",
    "electricity":             "CPI-U: Electricity",
    "utility_gas":             "CPI-U: Utility (piped) Gas Service",
    "core":                    "CPI-U: All Items Less Food and Energy (Core)",
    "core_goods":              "CPI-U: Core Goods",
    "apparel":                 "CPI-U: Apparel",
    "new_vehicles":            "CPI-U: New Vehicles",
    "used_cars_trucks":        "CPI-U: Used Cars and Trucks",
    "car_truck_rental":        "CPI-U: Car and Truck Rental",
    "medical_care":            "CPI-U: Medical Care",
    "medical_goods":           "CPI-U: Medical Care Commodities",
    "alcoholic_bev":           "CPI-U: Alcoholic Beverages",
    "tobacco":                 "CPI-U: Tobacco and Smoking Products",
    "core_services":           "CPI-U: Core Services",
    "shelter":                 "CPI-U: Shelter",
    "rent":                    "CPI-U: Rent of Primary Residence",
    "oer":                     "CPI-U: Owners' Equivalent Rent of Residences",
    "medical_services":        "CPI-U: Medical Care Services",
    "physicians_services":     "CPI-U: Physicians' Services",
    "hospital_services":       "CPI-U: Hospital Services",
    "transportation_services": "CPI-U: Transportation Services",
    "motor_vehicle_maint":     "CPI-U: Motor Vehicle Maintenance and Repair",
    "motor_vehicle_insur":     "CPI-U: Motor Vehicle Insurance",
    "public_transportation":   "CPI-U: Public Transportation",
    "airline_fares":           "CPI-U: Airline Fares",
    "lodging_away":            "CPI-U: Lodging Away from Home",
}

# Def BLS oficial apendada no `description` SQL pra cats com nome curto.
CATEGORY_BLS_DEFS = {
    "core_goods":    "Commodities less food and energy commodities (BLS item SACL1E)",
    "core_services": "Services less energy services (BLS item SASLE)",
}


# ============================================================================
# CUSTOM AGGREGATIONS — Laspeyres Dez-anchor (BLS canonico)
# Espelha scripts/bls_maps/custom_aggregations.csv + build_custom_aggregations.R.
# ============================================================================

CUSTOM_LABELS = {
    "rent_of_shelter":                           "CPI-U: Rent of Shelter (Custom)",
    "core_ex_oer":                               "CPI-U: Core ex OER (Custom)",
    "cpi_ex_oer":                                "CPI-U: All Items ex OER (Custom)",
    "core_services_ex_shelter":                  "CPI-U: Core Services ex Rent of Shelter (Custom)",
    "supercore_powell_old":                      "CPI-U: Core Services ex RPR & OER (Old Powell Supercore, Custom)",
    "core_services_ex_shelter_pubtrans_medical": "CPI-U: Core Services ex Shelter/PubTrans/Medical (Custom)",
    "super_super_core":                          "CPI-U: Super Super Core (Custom)",
    "core_services_ex_volatiles":                "CPI-U: Core Services ex Volatiles (Custom)",
}

# method: "exclude" (base - Σ excludes) ou "sum" (Σ includes).
CUSTOM_RECIPES: dict[str, dict] = {
    "rent_of_shelter": {
        "method": "sum", "base": None,
        "excludes": [], "includes": ["rent", "oer", "lodging_away"],
    },
    "core_ex_oer": {
        "method": "exclude", "base": "core",
        "excludes": ["oer"], "includes": [],
    },
    "cpi_ex_oer": {
        "method": "exclude", "base": "all_items",
        "excludes": ["oer"], "includes": [],
    },
    "core_services_ex_shelter": {
        "method": "exclude", "base": "core_services",
        "excludes": ["rent", "oer", "lodging_away"], "includes": [],
    },
    "supercore_powell_old": {
        "method": "exclude", "base": "core_services",
        "excludes": ["rent", "oer"], "includes": [],
    },
    "core_services_ex_shelter_pubtrans_medical": {
        "method": "exclude", "base": "core_services",
        "excludes": ["rent", "oer", "lodging_away", "public_transportation", "medical_services"],
        "includes": [],
    },
    "super_super_core": {
        "method": "exclude", "base": "core_services",
        "excludes": ["rent", "oer", "lodging_away", "airline_fares", "medical_services"],
        "includes": [],
    },
    "core_services_ex_volatiles": {
        "method": "exclude", "base": "core_services",
        "excludes": ["airline_fares", "medical_services"], "includes": [],
    },
}


def custom_deps(cats: Iterable[str]) -> set[str]:
    """Union das base cats necessarias pra construir as customs pedidas."""
    deps: set[str] = set()
    for c in cats:
        r = CUSTOM_RECIPES.get(c)
        if not r:
            continue
        if r["base"]:
            deps.add(r["base"])
        deps.update(r["excludes"])
        deps.update(r["includes"])
    return deps


# ============================================================================
# WEIGHT BASE — Relative Importance historica Table 6 BLS
# ATENCAO: RI_BASE_DATE deve refletir o mais recente ano em RI_HISTORICAL.
# Atualizar quando BLS publicar novo release em fev/YYYY.
# ============================================================================

RI_BASE_DATE = "2025-12"  # Ultimo ano-base disponivel em RI_HISTORICAL

# 26 anos (2000-2025) x 41 base cats. Parseado a partir de
# `data/cpi_cpius_pesos_annual.csv` (que por sua vez sai de
# `scripts/parse_historical_ri.py` sobre os arquivos Table 6 anuais).
# medical_care (SAM) eh derivado como SAM1+SAM2 no parser pros anos
# 2000-2002 (BLS Table 6 nao lista SAM diretamente nesses anos).
RI_HISTORICAL = {
    2000: {"airline_fares": 0.923, "alcoholic_bev": 0.981, "all_items": 100.0, "apparel": 4.453, "car_truck_rental": 0.138, "core": 77.102, "core_goods": 22.768, "core_services": 54.334, "electricity": 2.453, "energy": 7.681, "energy_commodities": 3.843, "energy_services": 3.838, "food": 15.217, "food_away": 5.658, "food_cereals_bakery": 1.522, "food_dairy": 1.05, "food_fruits_veg": 1.454, "food_home": 9.56, "food_meats": 2.573, "food_nonalc_bev": 1.026, "food_other_home": 1.935, "fuel_oil": 0.268, "gasoline": 3.458, "hospital_services": 1.371, "lodging_away": 2.346, "medical_care": 5.813, "medical_goods": 1.261, "medical_services": 4.552, "motor_fuel": 3.482, "motor_vehicle_insur": 2.413, "motor_vehicle_maint": 1.623, "new_vehicles": 4.677, "oer": 20.46, "physicians_services": 1.474, "public_transportation": 1.41, "rent": 7.079, "shelter": 30.251, "tobacco": 1.308, "transportation_services": 6.903, "used_cars_trucks": 1.887, "utility_gas": 1.385},
    2001: {"airline_fares": 0.761, "alcoholic_bev": 1.031, "all_items": 100.0, "apparel": 4.399, "car_truck_rental": 0.12, "core": 79.094, "core_goods": 23.86, "core_services": 55.234, "electricity": 2.521, "energy": 6.218, "energy_commodities": 2.752, "energy_services": 3.466, "food": 14.688, "food_away": 6.22, "food_cereals_bakery": 1.298, "food_dairy": 0.916, "food_fruits_veg": 1.204, "food_home": 8.468, "food_meats": 2.271, "food_nonalc_bev": 0.967, "food_other_home": 1.811, "fuel_oil": 0.121, "gasoline": 2.536, "hospital_services": 1.271, "lodging_away": 2.702, "medical_care": 5.81, "medical_goods": 1.377, "medical_services": 4.434, "motor_fuel": 2.564, "motor_vehicle_insur": 2.288, "motor_vehicle_maint": 1.4, "new_vehicles": 5.083, "oer": 22.046, "physicians_services": 1.503, "public_transportation": 1.211, "rent": 6.421, "shelter": 31.522, "tobacco": 0.928, "transportation_services": 6.638, "used_cars_trucks": 2.195, "utility_gas": 0.945},
    2002: {"airline_fares": 0.725, "alcoholic_bev": 1.029, "all_items": 100.0, "apparel": 4.22, "car_truck_rental": 0.118, "core": 78.724, "core_goods": 22.945, "core_services": 55.779, "electricity": 2.415, "energy": 6.723, "energy_commodities": 3.324, "energy_services": 3.399, "food": 14.554, "food_away": 6.216, "food_cereals_bakery": 1.281, "food_dairy": 0.876, "food_fruits_veg": 1.234, "food_home": 8.338, "food_meats": 2.222, "food_nonalc_bev": 0.954, "food_other_home": 1.771, "fuel_oil": 0.136, "gasoline": 3.091, "hospital_services": 1.367, "lodging_away": 2.654, "medical_care": 5.961, "medical_goods": 1.387, "medical_services": 4.574, "motor_fuel": 3.119, "motor_vehicle_insur": 2.436, "motor_vehicle_maint": 1.418, "new_vehicles": 4.864, "oer": 22.243, "physicians_services": 1.516, "public_transportation": 1.172, "rent": 6.467, "shelter": 31.728, "tobacco": 0.992, "transportation_services": 6.722, "used_cars_trucks": 2.025, "utility_gas": 0.984},
    2003: {"airline_fares": 0.634, "alcoholic_bev": 1.001, "all_items": 100.0, "apparel": 3.975, "car_truck_rental": 0.107, "core": 78.537, "core_goods": 22.254, "core_services": 56.283, "electricity": 2.431, "energy": 7.08, "energy_commodities": 3.48, "energy_services": 3.599, "food": 14.383, "food_away": 6.127, "food_cereals_bakery": 1.202, "food_dairy": 0.842, "food_fruits_veg": 1.221, "food_home": 8.256, "food_meats": 2.32, "food_nonalc_bev": 0.905, "food_other_home": 1.765, "fuel_oil": 0.151, "gasoline": 3.222, "hospital_services": 1.425, "lodging_away": 2.954, "medical_care": 6.074, "medical_goods": 1.499, "medical_services": 4.575, "motor_fuel": 3.249, "motor_vehicle_insur": 2.466, "motor_vehicle_maint": 1.349, "new_vehicles": 4.817, "oer": 23.383, "physicians_services": 1.545, "public_transportation": 1.064, "rent": 6.157, "shelter": 32.878, "tobacco": 0.806, "transportation_services": 6.319, "used_cars_trucks": 2.007, "utility_gas": 1.168},
    2004: {"airline_fares": 0.605, "alcoholic_bev": 0.996, "all_items": 100.0, "apparel": 3.841, "car_truck_rental": 0.1, "core": 77.714, "core_goods": 21.674, "core_services": 56.04, "electricity": 2.405, "energy": 7.991, "energy_commodities": 4.269, "energy_services": 3.722, "food": 14.295, "food_away": 6.113, "food_cereals_bakery": 1.185, "food_dairy": 0.849, "food_fruits_veg": 1.276, "food_home": 8.183, "food_meats": 2.272, "food_nonalc_bev": 0.884, "food_other_home": 1.716, "fuel_oil": 0.204, "gasoline": 3.934, "hospital_services": 1.452, "lodging_away": 3.008, "medical_care": 6.132, "medical_goods": 1.484, "medical_services": 4.649, "motor_fuel": 3.969, "motor_vehicle_insur": 2.47, "motor_vehicle_maint": 1.341, "new_vehicles": 4.692, "oer": 23.158, "physicians_services": 1.555, "public_transportation": 1.029, "rent": 6.133, "shelter": 32.686, "tobacco": 0.804, "transportation_services": 6.235, "used_cars_trucks": 2.037, "utility_gas": 1.317},
    2005: {"airline_fares": 0.673, "alcoholic_bev": 1.109, "all_items": 100.0, "apparel": 3.786, "car_truck_rental": 0.09, "core": 77.373, "core_goods": 22.319, "core_services": 55.055, "electricity": 2.625, "energy": 8.685, "energy_commodities": 4.53, "energy_services": 4.155, "food": 13.942, "food_away": 5.953, "food_cereals_bakery": 1.098, "food_dairy": 0.852, "food_fruits_veg": 1.219, "food_home": 7.988, "food_meats": 2.133, "food_nonalc_bev": 0.91, "food_other_home": 1.777, "fuel_oil": 0.232, "gasoline": 4.148, "hospital_services": 1.49, "lodging_away": 2.611, "medical_care": 6.22, "medical_goods": 1.457, "medical_services": 4.764, "motor_fuel": 4.191, "motor_vehicle_insur": 2.301, "motor_vehicle_maint": 1.131, "new_vehicles": 5.155, "oer": 23.442, "physicians_services": 1.631, "public_transportation": 1.087, "rent": 5.832, "shelter": 32.26, "tobacco": 0.71, "transportation_services": 5.707, "used_cars_trucks": 1.799, "utility_gas": 1.53},
    2006: {"airline_fares": 0.649, "alcoholic_bev": 1.107, "all_items": 100.0, "apparel": 3.726, "car_truck_rental": 0.09, "core": 77.401, "core_goods": 21.735, "core_services": 55.666, "electricity": 2.75, "energy": 8.715, "energy_commodities": 4.685, "energy_services": 4.029, "food": 13.885, "food_away": 5.989, "food_cereals_bakery": 1.103, "food_dairy": 0.821, "food_fruits_veg": 1.211, "food_home": 7.896, "food_meats": 2.112, "food_nonalc_bev": 0.906, "food_other_home": 1.743, "fuel_oil": 0.231, "gasoline": 4.303, "hospital_services": 1.542, "lodging_away": 2.648, "medical_care": 6.281, "medical_goods": 1.446, "medical_services": 4.834, "motor_fuel": 4.347, "motor_vehicle_insur": 2.261, "motor_vehicle_maint": 1.145, "new_vehicles": 4.982, "oer": 23.83, "physicians_services": 1.616, "public_transportation": 1.06, "rent": 5.93, "shelter": 32.776, "tobacco": 0.712, "transportation_services": 5.638, "used_cars_trucks": 1.716, "utility_gas": 1.28},
    2007: {"airline_fares": 0.721, "alcoholic_bev": 1.08, "all_items": 100.0, "apparel": 3.731, "car_truck_rental": 0.082, "core": 76.469, "core_goods": 21.602, "core_services": 54.867, "electricity": 2.766, "energy": 9.698, "energy_commodities": 5.834, "energy_services": 3.864, "food": 13.833, "food_away": 6.173, "food_cereals_bakery": 1.03, "food_dairy": 0.887, "food_fruits_veg": 1.156, "food_home": 7.66, "food_meats": 1.807, "food_nonalc_bev": 0.928, "food_other_home": 1.852, "fuel_oil": 0.239, "gasoline": 5.215, "hospital_services": 1.264, "lodging_away": 2.564, "medical_care": 6.231, "medical_goods": 1.601, "medical_services": 4.63, "motor_fuel": 5.482, "motor_vehicle_insur": 1.966, "motor_vehicle_maint": 1.123, "new_vehicles": 4.632, "oer": 23.942, "physicians_services": 1.326, "public_transportation": 1.106, "rent": 5.765, "shelter": 32.596, "tobacco": 0.731, "transportation_services": 5.35, "used_cars_trucks": 1.773, "utility_gas": 1.098},
    2008: {"airline_fares": 0.731, "alcoholic_bev": 1.127, "all_items": 100.0, "apparel": 3.691, "car_truck_rental": 0.085, "core": 77.746, "core_goods": 21.461, "core_services": 56.285, "electricity": 3.002, "energy": 7.624, "energy_commodities": 3.465, "energy_services": 4.159, "food": 14.629, "food_away": 6.474, "food_cereals_bakery": 1.15, "food_dairy": 0.91, "food_fruits_veg": 1.194, "food_home": 8.156, "food_meats": 1.898, "food_nonalc_bev": 0.982, "food_other_home": 2.022, "fuel_oil": 0.188, "gasoline": 2.964, "hospital_services": 1.337, "lodging_away": 2.478, "medical_care": 6.39, "medical_goods": 1.625, "medical_services": 4.765, "motor_fuel": 3.164, "motor_vehicle_insur": 2.042, "motor_vehicle_maint": 1.188, "new_vehicles": 4.48, "oer": 24.433, "physicians_services": 1.364, "public_transportation": 1.125, "rent": 5.957, "shelter": 33.2, "tobacco": 0.776, "transportation_services": 5.567, "used_cars_trucks": 1.628, "utility_gas": 1.157},
    2009: {"airline_fares": 0.783, "alcoholic_bev": 1.056, "all_items": 100.0, "apparel": 3.695, "car_truck_rental": 0.09, "core": 77.708, "core_goods": 21.276, "core_services": 56.432, "electricity": 2.845, "energy": 8.553, "energy_commodities": 4.801, "energy_services": 3.752, "food": 13.738, "food_away": 5.937, "food_cereals_bakery": 1.108, "food_dairy": 0.82, "food_fruits_veg": 1.153, "food_home": 7.801, "food_meats": 1.745, "food_nonalc_bev": 0.952, "food_other_home": 2.023, "fuel_oil": 0.179, "gasoline": 4.337, "hospital_services": 1.358, "lodging_away": 0.769, "medical_care": 6.513, "medical_goods": 1.611, "medical_services": 4.902, "motor_fuel": 4.525, "motor_vehicle_insur": 2.492, "motor_vehicle_maint": 1.167, "new_vehicles": 3.573, "oer": 25.206, "physicians_services": 1.45, "public_transportation": 1.187, "rent": 5.966, "shelter": 32.289, "tobacco": 0.871, "transportation_services": 6.06, "used_cars_trucks": 2.012, "utility_gas": 0.907},
    2010: {"airline_fares": 0.816, "alcoholic_bev": 1.051, "all_items": 100.0, "apparel": 3.601, "car_truck_rental": 0.088, "core": 77.179, "core_goods": 20.882, "core_services": 56.297, "electricity": 2.823, "energy": 9.079, "energy_commodities": 5.388, "energy_services": 3.691, "food": 13.742, "food_away": 5.926, "food_cereals_bakery": 1.09, "food_dairy": 0.839, "food_fruits_veg": 1.152, "food_home": 7.816, "food_meats": 1.813, "food_nonalc_bev": 0.926, "food_other_home": 1.996, "fuel_oil": 0.205, "gasoline": 4.865, "hospital_services": 1.44, "lodging_away": 0.776, "medical_care": 6.627, "medical_goods": 1.633, "medical_services": 4.994, "motor_fuel": 5.079, "motor_vehicle_insur": 2.563, "motor_vehicle_maint": 1.172, "new_vehicles": 3.513, "oer": 24.905, "physicians_services": 1.477, "public_transportation": 1.227, "rent": 5.925, "shelter": 31.955, "tobacco": 0.906, "transportation_services": 6.14, "used_cars_trucks": 2.055, "utility_gas": 0.869},
    2011: {"airline_fares": 0.768, "alcoholic_bev": 0.948, "all_items": 100.0, "apparel": 3.562, "car_truck_rental": 0.071, "core": 76.013, "core_goods": 19.852, "core_services": 56.161, "electricity": 2.913, "energy": 9.679, "energy_commodities": 5.806, "energy_services": 3.873, "food": 14.308, "food_away": 5.669, "food_cereals_bakery": 1.242, "food_dairy": 0.916, "food_fruits_veg": 1.287, "food_home": 8.638, "food_meats": 1.96, "food_nonalc_bev": 0.961, "food_other_home": 2.272, "fuel_oil": 0.229, "gasoline": 5.273, "hospital_services": 1.51, "lodging_away": 0.749, "medical_care": 7.061, "medical_goods": 1.716, "medical_services": 5.345, "motor_fuel": 5.463, "motor_vehicle_insur": 2.426, "motor_vehicle_maint": 1.155, "new_vehicles": 3.195, "oer": 23.957, "physicians_services": 1.612, "public_transportation": 1.181, "rent": 6.485, "shelter": 31.539, "tobacco": 0.804, "transportation_services": 5.797, "used_cars_trucks": 1.913, "utility_gas": 0.96},
    2012: {"airline_fares": 0.771, "alcoholic_bev": 0.949, "all_items": 100.0, "apparel": 3.564, "car_truck_rental": 0.07, "core": 76.127, "core_goods": 19.574, "core_services": 56.553, "electricity": 2.85, "energy": 9.561, "energy_commodities": 5.795, "energy_services": 3.767, "food": 14.312, "food_away": 5.713, "food_cereals_bakery": 1.231, "food_dairy": 0.905, "food_fruits_veg": 1.287, "food_home": 8.598, "food_meats": 1.955, "food_nonalc_bev": 0.943, "food_other_home": 2.278, "fuel_oil": 0.234, "gasoline": 5.274, "hospital_services": 1.557, "lodging_away": 0.741, "medical_care": 7.163, "medical_goods": 1.714, "medical_services": 5.448, "motor_fuel": 5.462, "motor_vehicle_insur": 2.497, "motor_vehicle_maint": 1.149, "new_vehicles": 3.189, "oer": 24.041, "physicians_services": 1.616, "public_transportation": 1.189, "rent": 6.545, "shelter": 31.681, "tobacco": 0.805, "transportation_services": 5.848, "used_cars_trucks": 1.844, "utility_gas": 0.917},
    2013: {"airline_fares": 0.742, "alcoholic_bev": 1.01, "all_items": 100.0, "apparel": 3.437, "car_truck_rental": 0.073, "core": 77.063, "core_goods": 19.71, "core_services": 57.353, "electricity": 2.872, "energy": 9.046, "energy_commodities": 5.34, "energy_services": 3.705, "food": 13.891, "food_away": 5.704, "food_cereals_bakery": 1.141, "food_dairy": 0.86, "food_fruits_veg": 1.346, "food_home": 8.187, "food_meats": 1.859, "food_nonalc_bev": 0.955, "food_other_home": 2.027, "fuel_oil": 0.173, "gasoline": 4.979, "hospital_services": 1.78, "lodging_away": 0.795, "medical_care": 7.551, "medical_goods": 1.704, "medical_services": 5.847, "motor_fuel": 5.065, "motor_vehicle_insur": 2.213, "motor_vehicle_maint": 1.153, "new_vehicles": 3.559, "oer": 23.9, "physicians_services": 1.579, "public_transportation": 1.164, "rent": 6.977, "shelter": 32.029, "tobacco": 0.703, "transportation_services": 5.571, "used_cars_trucks": 1.673, "utility_gas": 0.834},
    2014: {"airline_fares": 0.702, "alcoholic_bev": 1.015, "all_items": 100.0, "apparel": 3.343, "car_truck_rental": 0.073, "core": 77.713, "core_goods": 19.408, "core_services": 58.305, "electricity": 2.94, "energy": 8.03, "energy_commodities": 4.215, "energy_services": 3.815, "food": 14.257, "food_away": 5.83, "food_cereals_bakery": 1.138, "food_dairy": 0.898, "food_fruits_veg": 1.379, "food_home": 8.427, "food_meats": 2.014, "food_nonalc_bev": 0.955, "food_other_home": 2.043, "fuel_oil": 0.139, "gasoline": 3.904, "hospital_services": 1.853, "lodging_away": 0.839, "medical_care": 7.716, "medical_goods": 1.772, "medical_services": 5.944, "motor_fuel": 3.979, "motor_vehicle_insur": 2.3, "motor_vehicle_maint": 1.168, "new_vehicles": 3.551, "oer": 24.339, "physicians_services": 1.59, "public_transportation": 1.122, "rent": 7.159, "shelter": 32.711, "tobacco": 0.718, "transportation_services": 5.625, "used_cars_trucks": 1.591, "utility_gas": 0.875},
    2015: {"airline_fares": 0.669, "alcoholic_bev": 0.958, "all_items": 100.0, "apparel": 3.101, "car_truck_rental": 0.095, "core": 79.169, "core_goods": 19.613, "core_services": 59.556, "electricity": 2.833, "energy": 6.816, "energy_commodities": 3.228, "energy_services": 3.588, "food": 14.015, "food_away": 5.785, "food_cereals_bakery": 1.098, "food_dairy": 0.846, "food_fruits_veg": 1.399, "food_home": 8.23, "food_meats": 1.876, "food_nonalc_bev": 0.977, "food_other_home": 2.033, "fuel_oil": 0.093, "gasoline": 3.0, "hospital_services": 2.19, "lodging_away": 0.841, "medical_care": 8.375, "medical_goods": 1.806, "medical_services": 6.569, "motor_fuel": 3.048, "motor_vehicle_insur": 2.379, "motor_vehicle_maint": 1.167, "new_vehicles": 3.742, "oer": 24.227, "physicians_services": 1.681, "public_transportation": 1.135, "rent": 7.733, "shelter": 33.15, "tobacco": 0.655, "transportation_services": 5.876, "used_cars_trucks": 2.101, "utility_gas": 0.755},
    2016: {"airline_fares": 0.624, "alcoholic_bev": 0.952, "all_items": 100.0, "apparel": 3.034, "car_truck_rental": 0.103, "core": 79.263, "core_goods": 19.101, "core_services": 60.162, "electricity": 2.794, "energy": 7.039, "energy_commodities": 3.447, "energy_services": 3.592, "food": 13.698, "food_away": 5.799, "food_cereals_bakery": 1.068, "food_dairy": 0.818, "food_fruits_veg": 1.338, "food_home": 7.899, "food_meats": 1.74, "food_nonalc_bev": 0.949, "food_other_home": 1.986, "fuel_oil": 0.102, "gasoline": 3.208, "hospital_services": 2.241, "lodging_away": 0.851, "medical_care": 8.539, "medical_goods": 1.852, "medical_services": 6.687, "motor_fuel": 3.257, "motor_vehicle_insur": 2.494, "motor_vehicle_maint": 1.165, "new_vehicles": 3.678, "oer": 24.583, "physicians_services": 1.71, "public_transportation": 1.086, "rent": 7.875, "shelter": 33.652, "tobacco": 0.665, "transportation_services": 5.92, "used_cars_trucks": 1.986, "utility_gas": 0.798},
    2017: {"airline_fares": 0.691, "alcoholic_bev": 0.974, "all_items": 100.0, "apparel": 3.018, "car_truck_rental": 0.117, "core": 79.103, "core_goods": 19.849, "core_services": 59.254, "electricity": 2.628, "energy": 7.513, "energy_commodities": 4.094, "energy_services": 3.419, "food": 13.384, "food_away": 6.002, "food_cereals_bakery": 0.964, "food_dairy": 0.744, "food_fruits_veg": 1.302, "food_home": 7.382, "food_meats": 1.635, "food_nonalc_bev": 0.873, "food_other_home": 1.864, "fuel_oil": 0.109, "gasoline": 3.823, "hospital_services": 2.3, "lodging_away": 0.898, "medical_care": 8.673, "medical_goods": 1.748, "medical_services": 6.924, "motor_fuel": 3.908, "motor_vehicle_insur": 2.352, "motor_vehicle_maint": 1.123, "new_vehicles": 3.805, "oer": 23.747, "physicians_services": 1.755, "public_transportation": 1.153, "rent": 7.823, "shelter": 32.843, "tobacco": 0.651, "transportation_services": 5.926, "used_cars_trucks": 2.402, "utility_gas": 0.791},
    2018: {"airline_fares": 0.66, "alcoholic_bev": 0.973, "all_items": 100.0, "apparel": 2.959, "car_truck_rental": 0.122, "core": 79.312, "core_goods": 19.503, "core_services": 59.809, "electricity": 2.607, "energy": 7.347, "energy_commodities": 3.947, "energy_services": 3.4, "food": 13.341, "food_away": 6.055, "food_cereals_bakery": 0.962, "food_dairy": 0.729, "food_fruits_veg": 1.298, "food_home": 7.286, "food_meats": 1.597, "food_nonalc_bev": 0.868, "food_other_home": 1.832, "fuel_oil": 0.109, "gasoline": 3.671, "hospital_services": 2.34, "lodging_away": 0.887, "medical_care": 8.682, "medical_goods": 1.707, "medical_services": 6.974, "motor_fuel": 3.762, "motor_vehicle_insur": 2.415, "motor_vehicle_maint": 1.128, "new_vehicles": 3.724, "oer": 24.054, "physicians_services": 1.732, "public_transportation": 1.113, "rent": 7.943, "shelter": 33.259, "tobacco": 0.661, "transportation_services": 5.975, "used_cars_trucks": 2.391, "utility_gas": 0.794},
    2019: {"airline_fares": 0.786, "alcoholic_bev": 1.023, "all_items": 100.0, "apparel": 2.81, "car_truck_rental": 0.129, "core": 79.524, "core_goods": 20.137, "core_services": 59.387, "electricity": 2.405, "energy": 6.706, "energy_commodities": 3.61, "energy_services": 3.096, "food": 13.771, "food_away": 6.191, "food_cereals_bakery": 0.984, "food_dairy": 0.768, "food_fruits_veg": 1.317, "food_home": 7.579, "food_meats": 1.682, "food_nonalc_bev": 0.903, "food_other_home": 1.925, "fuel_oil": 0.106, "gasoline": 3.362, "hospital_services": 2.186, "lodging_away": 0.924, "medical_care": 8.833, "medical_goods": 1.643, "medical_services": 7.19, "motor_fuel": 3.44, "motor_vehicle_insur": 1.701, "motor_vehicle_maint": 1.077, "new_vehicles": 3.734, "oer": 24.071, "physicians_services": 1.811, "public_transportation": 1.274, "rent": 7.792, "shelter": 33.158, "tobacco": 0.587, "transportation_services": 5.399, "used_cars_trucks": 2.533, "utility_gas": 0.691},
    2020: {"airline_fares": 0.633, "alcoholic_bev": 1.038, "all_items": 100.0, "apparel": 2.663, "car_truck_rental": 0.134, "core": 79.726, "core_goods": 20.2, "core_services": 59.526, "electricity": 2.425, "energy": 6.155, "energy_commodities": 3.02, "energy_services": 3.135, "food": 14.119, "food_away": 6.347, "food_cereals_bakery": 1.001, "food_dairy": 0.792, "food_fruits_veg": 1.341, "food_home": 7.772, "food_meats": 1.736, "food_nonalc_bev": 0.93, "food_other_home": 1.972, "fuel_oil": 0.084, "gasoline": 2.811, "hospital_services": 2.221, "lodging_away": 0.825, "medical_care": 8.87, "medical_goods": 1.58, "medical_services": 7.289, "motor_fuel": 2.875, "motor_vehicle_insur": 1.598, "motor_vehicle_maint": 1.099, "new_vehicles": 3.756, "oer": 24.263, "physicians_services": 1.817, "public_transportation": 1.105, "rent": 7.862, "shelter": 33.316, "tobacco": 0.608, "transportation_services": 5.142, "used_cars_trucks": 2.75, "utility_gas": 0.71},
    2021: {"airline_fares": 0.481, "alcoholic_bev": 0.889, "all_items": 100.0, "apparel": 2.458, "car_truck_rental": 0.153, "core": 79.282, "core_goods": 21.699, "core_services": 57.583, "electricity": 2.454, "energy": 7.348, "energy_commodities": 4.014, "energy_services": 3.334, "food": 13.37, "food_away": 5.205, "food_cereals_bakery": 1.03, "food_dairy": 0.752, "food_fruits_veg": 1.408, "food_home": 8.165, "food_meats": 1.888, "food_nonalc_bev": 0.933, "food_other_home": 2.153, "fuel_oil": 0.115, "gasoline": 3.748, "hospital_services": 2.199, "lodging_away": 0.914, "medical_care": 8.487, "medical_goods": 1.524, "medical_services": 6.962, "motor_fuel": 3.822, "motor_vehicle_insur": 2.383, "motor_vehicle_maint": 1.038, "new_vehicles": 4.105, "oer": 24.251, "physicians_services": 1.9, "public_transportation": 0.777, "rent": 7.398, "shelter": 32.946, "tobacco": 0.526, "transportation_services": 5.599, "used_cars_trucks": 4.143, "utility_gas": 0.879},
    2022: {"airline_fares": 0.587, "alcoholic_bev": 0.845, "all_items": 100.0, "apparel": 2.479, "car_truck_rental": 0.127, "core": 79.548, "core_goods": 21.361, "core_services": 58.187, "electricity": 2.541, "energy": 6.921, "energy_commodities": 3.49, "energy_services": 3.431, "food": 13.531, "food_away": 4.803, "food_cereals_bakery": 1.164, "food_dairy": 0.818, "food_fruits_veg": 1.512, "food_home": 8.728, "food_meats": 1.847, "food_nonalc_bev": 1.039, "food_other_home": 2.347, "fuel_oil": 0.15, "gasoline": 3.172, "hospital_services": 1.94, "lodging_away": 1.085, "medical_care": 8.108, "medical_goods": 1.455, "medical_services": 6.653, "motor_fuel": 3.275, "motor_vehicle_insur": 2.511, "motor_vehicle_maint": 1.104, "new_vehicles": 4.313, "oer": 25.424, "physicians_services": 1.855, "public_transportation": 0.785, "rent": 7.528, "shelter": 34.413, "tobacco": 0.494, "transportation_services": 5.75, "used_cars_trucks": 2.668, "utility_gas": 0.89},
    2023: {"airline_fares": 0.751, "alcoholic_bev": 0.854, "all_items": 100.0, "apparel": 2.512, "car_truck_rental": 0.139, "core": 79.79, "core_goods": 18.891, "core_services": 60.899, "electricity": 2.428, "energy": 6.655, "energy_commodities": 3.539, "energy_services": 3.116, "food": 13.555, "food_away": 5.388, "food_cereals_bakery": 1.066, "food_dairy": 0.748, "food_fruits_veg": 1.41, "food_home": 8.167, "food_meats": 1.722, "food_nonalc_bev": 1.027, "food_other_home": 2.193, "fuel_oil": 0.084, "gasoline": 3.261, "hospital_services": 1.987, "lodging_away": 1.338, "medical_care": 8.004, "medical_goods": 1.489, "medical_services": 6.515, "motor_fuel": 3.372, "motor_vehicle_insur": 2.794, "motor_vehicle_maint": 1.233, "new_vehicles": 3.684, "oer": 26.769, "physicians_services": 1.828, "public_transportation": 1.071, "rent": 7.671, "shelter": 36.191, "tobacco": 0.542, "transportation_services": 6.294, "used_cars_trucks": 2.012, "utility_gas": 0.688},
    2024: {"airline_fares": 0.918, "alcoholic_bev": 0.835, "all_items": 100.0, "apparel": 2.48, "car_truck_rental": 0.13, "core": 80.094, "core_goods": 19.388, "core_services": 60.705, "electricity": 2.343, "energy": 6.216, "energy_commodities": 3.122, "energy_services": 3.094, "food": 13.691, "food_away": 5.648, "food_cereals_bakery": 1.11, "food_dairy": 0.741, "food_fruits_veg": 1.336, "food_home": 8.043, "food_meats": 1.621, "food_nonalc_bev": 0.897, "food_other_home": 2.338, "fuel_oil": 0.074, "gasoline": 2.902, "hospital_services": 1.932, "lodging_away": 1.292, "medical_care": 8.273, "medical_goods": 1.527, "medical_services": 6.747, "motor_fuel": 2.983, "motor_vehicle_insur": 2.796, "motor_vehicle_maint": 1.019, "new_vehicles": 4.393, "oer": 26.282, "physicians_services": 1.824, "public_transportation": 1.468, "rent": 7.499, "shelter": 35.483, "tobacco": 0.482, "transportation_services": 6.305, "used_cars_trucks": 2.391, "utility_gas": 0.75},
    2025: {"airline_fares": 0.881, "alcoholic_bev": 0.84, "all_items": 100.0, "apparel": 2.368, "car_truck_rental": 0.138, "core": 79.919, "core_goods": 19.176, "core_services": 60.744, "electricity": 2.489, "energy": 6.383, "energy_commodities": 3.12, "energy_services": 3.262, "food": 13.698, "food_away": 5.373, "food_cereals_bakery": 1.035, "food_dairy": 0.758, "food_fruits_veg": 1.269, "food_home": 8.325, "food_meats": 1.995, "food_nonalc_bev": 0.995, "food_other_home": 2.273, "fuel_oil": 0.083, "gasoline": 2.895, "hospital_services": 2.167, "lodging_away": 1.289, "medical_care": 8.423, "medical_goods": 1.489, "medical_services": 6.935, "motor_fuel": 2.981, "motor_vehicle_insur": 2.754, "motor_vehicle_maint": 1.039, "new_vehicles": 3.838, "oer": 26.204, "physicians_services": 1.684, "public_transportation": 1.485, "rent": 7.84, "shelter": 35.625, "tobacco": 0.445, "transportation_services": 6.315, "used_cars_trucks": 2.759, "utility_gas": 0.773},
}


# ============================================================================
# CONSTANTES DE PROTOCOLO
# ============================================================================

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
CODE_FMT = "CPIUS:{cat}"                  # sync 2026-07-20: sem sufixo /Index
TOP3 = ("food", "energy", "core")         # renormalizacao Weight
DEFAULT_START_YEAR = 2000
DEFAULT_END_YEAR = date.today().year

# Janela de replace incremental no SQL. Toda re-run so re-envia os ultimos N
# meses de cada serie (DELETE + INSERT restrito). Cobre revisoes SA anuais
# tipicas (BLS revisa ate 5 anos em fev/YYYY, mas 24m pega 99% dos casos
# praticos) e recalculo de Weight, que so depende de RI(base_year)+idx dentro
# do proprio ano. Primeira insercao de uma serie (SELECT nao retorna nada)
# ainda faz full seed. Custo por run: ~O(24 x n_cats) vs ~O(300 x n_cats).
INCREMENTAL_MONTHS = 24


# ============================================================================
# PARSE INPUT
# ============================================================================

def parse_input(cats_arg: str | None, codes_arg: str | None) -> set[str]:
    """Aceita --cats (lista de cats) ou --codes (lista de bls_codes CPIUS:*).
    Retorna set de cats validas (base + customs). Keywords: 'all' pra tudo,
    'all-base' so ITEM_CODES, 'all-customs' so CUSTOM_RECIPES."""
    if not cats_arg and not codes_arg:
        sys.exit("[ERR] --cats ou --codes obrigatorio")

    known = set(ITEM_CODES.keys()) | set(CUSTOM_RECIPES.keys())
    cats: set[str] = set()
    if cats_arg:
        raw_cats = [c.strip() for c in cats_arg.split(",") if c.strip()]
        keywords = {c.lower() for c in raw_cats}
        if "all" in keywords:
            cats.update(ITEM_CODES.keys())
            cats.update(CUSTOM_RECIPES.keys())
        if "all-base" in keywords:
            cats.update(ITEM_CODES.keys())
        if "all-customs" in keywords:
            cats.update(CUSTOM_RECIPES.keys())
        raw_cats = [c for c in raw_cats if c.lower() not in {"all", "all-base", "all-customs"}]
        cats.update(raw_cats)
    if codes_arg:
        for raw in codes_arg.split(","):
            raw = raw.strip()
            if not raw:
                continue
            if not raw.startswith("CPIUS:"):
                sys.exit(f"[ERR] bls_code fora do padrao CPIUS: {raw!r}")
            # Aceita "CPIUS:cat" ou legacy "CPIUS:cat/Index"
            cat = raw.split(":", 1)[1].split("/", 1)[0]
            cats.add(cat)

    unknown = [c for c in cats if c not in known]
    if unknown:
        sys.exit(
            f"[ERR] cats desconhecidas: {unknown}. Suportadas: "
            f"{len(ITEM_CODES)} base cats + {len(CUSTOM_RECIPES)} customs. "
            f"Keywords: 'all', 'all-base', 'all-customs'."
        )
    return cats


# ============================================================================
# BLS API v2 FETCH
# ============================================================================

def fetch_bls_batched(
    series_ids: list[str],
    start_year: int,
    end_year: int,
    api_key: str | None,
) -> dict[str, pd.Series]:
    """POSTa BLS API v2 em batches. Retorna {series_id: Series indexed by month-start date}.
    Sem chave: 25 series/batch e 10 anos/janela. Com chave: 50 e 20."""
    max_per_batch = 50 if api_key else 25
    max_years = 20 if api_key else 10

    windows: list[tuple[int, int]] = []
    y0 = start_year
    while y0 <= end_year:
        y1 = min(y0 + max_years - 1, end_year)
        windows.append((y0, y1))
        y0 = y1 + 1

    log(f"[fetch] {len(series_ids)} series_ids x {len(windows)} janela(s) "
        f"({max_years}a) x batches de {max_per_batch}"
        f"  (API key {'ON' if api_key else 'OFF'})")

    accum: dict[str, dict[pd.Timestamp, float]] = {sid: {} for sid in series_ids}
    total_batches = len(windows) * ((len(series_ids) + max_per_batch - 1) // max_per_batch)
    b_ix = 0
    for (yw0, yw1) in windows:
        for i in range(0, len(series_ids), max_per_batch):
            b_ix += 1
            batch = series_ids[i:i + max_per_batch]
            payload = {
                "seriesid": batch,
                "startyear": str(yw0),
                "endyear": str(yw1),
            }
            if api_key:
                payload["registrationkey"] = api_key
            t_req = time.monotonic()
            log(f"  batch {b_ix}/{total_batches} [{yw0}-{yw1}] POST {len(batch)} ids...")
            resp = requests.post(BLS_API_URL, json=payload, timeout=90)
            resp.raise_for_status()
            j = resp.json()
            if j.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError(f"[BLS] {j.get('status')}: {j.get('message')}")
            n_new = 0
            for s in j["Results"]["series"]:
                sid = s["seriesID"]
                for pt in s["data"]:
                    if pt["period"] == "M13":  # media anual — pula
                        continue
                    d = pd.Timestamp(int(pt["year"]), int(pt["period"][1:]), 1)
                    try:
                        accum[sid][d] = float(pt["value"])
                        n_new += 1
                    except (ValueError, TypeError):
                        continue
            log(f"    done in {time.monotonic()-t_req:.1f}s  (+{n_new} obs, "
                f"acumulado={sum(len(v) for v in accum.values())})")

    out = {}
    n_empty = 0
    for sid, obs in accum.items():
        if not obs:
            log(f"  [WARN] sem dados: {sid}")
            n_empty += 1
            continue
        s = pd.Series(obs).sort_index()
        s.name = sid
        out[sid] = s
    log(f"[fetch] concluido: {len(out)}/{len(series_ids)} series c/ dados "
        f"({n_empty} vazias)")
    return out


def build_series_ids(cats: Iterable[str]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """Constroi lista de series IDs CUUR/CUSR + mapping id -> (cat, sa_flag)."""
    ids: list[str] = []
    id_map: dict[str, tuple[str, str]] = {}
    for cat in sorted(cats):
        item = ITEM_CODES[cat]
        for prefix, sa in (("CUUR", "NSA"), ("CUSR", "SA")):
            sid = f"{prefix}0000{item}"
            ids.append(sid)
            id_map[sid] = (cat, sa)
    return ids, id_map


# ============================================================================
# REBASE + WEIGHT
# ============================================================================

def rebase_jan2000(s: pd.Series) -> pd.Series:
    """Rebase pra jan/2000=100. Se jan/2000 nao existe, usa primeiro ponto."""
    base_date = pd.Timestamp(2000, 1, 1)
    if base_date in s.index:
        base = s.loc[base_date]
    else:
        base = s.iloc[0]
    return (s / base) * 100.0


def compute_weights(idx_nsa: pd.DataFrame, requested_cats: set[str]) -> pd.DataFrame:
    """Aplica ajuste implicito BLS. Renormaliza food+energy+core=100 e forca
    all_items=100.0. Retorna DataFrame long (date, cat, weight).

    `idx_nsa` deve ser wide: index=date, columns=cats (incluindo TOP3).
    Retorna Weight so pras `requested_cats` (nao inclui TOP3 se nao pedidas)."""
    anos_base = sorted(RI_HISTORICAL.keys())
    all_cats_needed = set(idx_nsa.columns)

    def base_year(m: pd.Timestamp) -> int:
        y = m.year
        cand = y - 1
        if cand in anos_base:
            return cand
        le = [a for a in anos_base if a <= y]
        return max(le) if le else min(anos_base)

    def dec_key(y: int) -> pd.Timestamp:
        return pd.Timestamp(y, 12, 1)

    rows = []
    for m in idx_nsa.index:
        by = base_year(m)
        ri_row = RI_HISTORICAL[by]
        dk = dec_key(by)
        idx_dez = idx_nsa.loc[dk] if dk in idx_nsa.index else idx_nsa.loc[m]
        idx_m = idx_nsa.loc[m]
        w = {}
        for c in all_cats_needed:
            ri = ri_row.get(c)
            if ri is None:
                continue
            i_m = idx_m.get(c)
            i_d = idx_dez.get(c)
            if pd.isna(i_m) or pd.isna(i_d) or i_d == 0:
                w[c] = ri  # fallback: peso base sem ajuste
            else:
                w[c] = ri * (i_m / i_d)
        s3 = sum(w.get(c, 0) or 0 for c in TOP3)
        if s3 > 0:
            factor = 100.0 / s3
            w = {c: v * factor for c, v in w.items()}
        # Force all_items=100.0 constante
        if "all_items" in w:
            w["all_items"] = 100.0
        for c in requested_cats:
            if c in w:
                rows.append({"date": m, "cat": c, "weight": w[c]})

    return pd.DataFrame(rows)


# ============================================================================
# CUSTOM BUILDERS — Laspeyres Dez-anchor (BLS canonico)
# ============================================================================

def build_custom_idx(
    recipe: dict,
    idx_wide: pd.DataFrame,   # index=date (month-start), cols=base cats
    peso_wide: pd.DataFrame,  # index=date (month-start), cols=base cats
) -> pd.Series:
    """Constroi indice custom via Laspeyres Dez-anchor. Pivot p/ mes m = Dez do
    ano-1 (fallback jan/2000 pra 2000). Formulas:
      exclude: I_ex(m) = I_ex(pivot) * [w_b_p·(I_b_m/I_b_p) - Σ w_e_p·(I_e_m/I_e_p)] /
                                       [w_b_p - Σ w_e_p]
      sum:     I_agg(m) = I_agg(pivot) * Σ w_i_p·(I_i_m/I_i_p) / Σ w_i_p"""
    method = recipe["method"]
    base = recipe["base"]
    excl = list(recipe["excludes"])
    incl = list(recipe["includes"])

    dates = idx_wide.index
    idx_out = pd.Series(index=dates, dtype=float)
    if len(dates) == 0:
        return idx_out
    idx_out.iloc[0] = 100.0  # jan/2000 = 100
    first_date = dates[0]

    for k in range(1, len(dates)):
        m = dates[k]
        pivot = pd.Timestamp(m.year - 1, 12, 1)
        if pivot < first_date:
            pivot = first_date
        if pivot not in idx_wide.index or pivot not in peso_wide.index:
            continue
        if pivot not in idx_out.index:
            continue
        i_pivot = idx_out.loc[pivot]
        if not pd.notna(i_pivot):
            continue

        irow_m = idx_wide.loc[m]
        irow_p = idx_wide.loc[pivot]
        wrow_p = peso_wide.loc[pivot]

        if method == "exclude":
            i_b_m = irow_m.get(base)
            i_b_p = irow_p.get(base)
            w_b_p = wrow_p.get(base)
            if not (pd.notna(i_b_m) and pd.notna(i_b_p) and pd.notna(w_b_p) and i_b_p > 0):
                continue
            num = w_b_p * (i_b_m / i_b_p)
            den = w_b_p
            ok = True
            for e in excl:
                i_e_m = irow_m.get(e)
                i_e_p = irow_p.get(e)
                w_e_p = wrow_p.get(e)
                if not (pd.notna(i_e_m) and pd.notna(i_e_p) and pd.notna(w_e_p) and i_e_p > 0):
                    ok = False
                    break
                num -= w_e_p * (i_e_m / i_e_p)
                den -= w_e_p
            if ok and den > 0:
                idx_out.iloc[k] = i_pivot * (num / den)
        else:  # sum
            num = 0.0
            den = 0.0
            ok = len(incl) > 0
            for c in incl:
                i_m = irow_m.get(c)
                i_p = irow_p.get(c)
                w_p = wrow_p.get(c)
                if not (pd.notna(i_m) and pd.notna(i_p) and pd.notna(w_p) and i_p > 0):
                    ok = False
                    break
                num += w_p * (i_m / i_p)
                den += w_p
            if ok and den > 0:
                idx_out.iloc[k] = i_pivot * (num / den)

    return idx_out


def build_custom_weight(recipe: dict, peso_wide: pd.DataFrame) -> pd.Series:
    """Peso mensal do agregado custom, usando pesos mensais ja ajustados."""
    method = recipe["method"]
    base = recipe["base"]
    excl = list(recipe["excludes"])
    incl = list(recipe["includes"])

    if method == "exclude":
        if base not in peso_wide.columns:
            return pd.Series(dtype=float)
        s = peso_wide[base].copy()
        for e in excl:
            if e not in peso_wide.columns:
                return pd.Series(dtype=float)
            s = s - peso_wide[e]
    else:  # sum
        if not incl or not all(c in peso_wide.columns for c in incl):
            return pd.Series(dtype=float)
        s = peso_wide[incl].sum(axis=1)

    return s.where(s > 0).dropna()


# ============================================================================
# SQL UPSERT (mirror sidra_to_sql de load_cpius_to_sql.py)
# ============================================================================

def upsert_series(
    session,
    country: str, subject: str, indicator: str,
    series_name: str, data_type: str, frequency: str,
    description: str, bls_code: str,
    series: pd.Series,
) -> int:
    """Upsert em OPT_Macro_Series_2 + replace incremental (ultimos N meses) em
    OPT_Macro_Series_Data_2. Se serie nao tem nenhuma linha ainda, faz seed
    full. Vintage nao eh preservada (release_date=today em tudo que reescreve)."""
    df_existing = pd.read_sql(
        """SELECT series_id FROM OPT_Macro_Series_2
           WHERE country=? AND subject=? AND indicator=?
             AND series_name=? AND data_type=?""",
        session.conn,
        params=[country, subject, indicator, series_name, data_type],
    )
    if df_existing.empty:
        meta = pd.DataFrame([{
            "country": country, "subject": subject, "indicator": indicator,
            "series_name": series_name, "data_type": data_type,
            "frequency": frequency, "description": description,
            "bls_code": bls_code,
        }])
        session.write_sql_table_from_dataframe("OPT_Macro_Series_2", meta, chunk_size=50)
        df_new = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country=? AND subject=? AND indicator=?
                 AND series_name=? AND data_type=?""",
            session.conn,
            params=[country, subject, indicator, series_name, data_type],
        )
        sid = int(df_new.iloc[0]["series_id"])
    else:
        sid = int(df_existing.iloc[0]["series_id"])

    s = series.dropna()
    if s.empty:
        return sid

    # Detecta se ja existe alguma linha em Data_2 pra decidir seed full vs incremental
    df_check = pd.read_sql(
        "SELECT TOP 1 date FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
        session.conn,
        params=[sid],
    )
    has_data = not df_check.empty

    if has_data:
        # Incremental: recorta os ultimos N meses da serie e faz DELETE+INSERT
        # so nessa janela. Comparacao SQL usa start-of-month; jan/2024 stored
        # como 2024-01-31 sempre satisfaz `>= 2024-01-01`.
        last_m = s.index.max()
        cutoff_som = pd.Timestamp(last_m.year, last_m.month, 1) - pd.DateOffset(
            months=INCREMENTAL_MONTHS - 1
        )
        cutoff_som = pd.Timestamp(cutoff_som.year, cutoff_som.month, 1)
        s = s[s.index >= cutoff_som]
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ? AND date >= ?",
            params=[sid, cutoff_som.date()],
        )
        log(f"      incremental (>= {cutoff_som:%Y-%m}): {len(s)} rows")
    else:
        # Primeira vez pra essa serie no SQL: seed full
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
            params=[sid],
        )
        log(f"      seed full (primeira vez): {len(s)} rows")

    today = date.today()
    dates_eom = (pd.to_datetime(s.index) + pd.offsets.MonthEnd(0)).date
    df_data = pd.DataFrame({
        "date": dates_eom, "series_id": sid, "value": s.values,
        "release_date": today, "vintage_date": today,
    })
    session.write_sql_table_from_dataframe(
        "OPT_Macro_Series_Data_2",
        df_data[["date", "series_id", "value", "release_date", "vintage_date"]],
        chunk_size=5_000,
    )
    return sid


# ============================================================================
# SIMULATE MODE (pra rodar local sem opt_utils)
# ============================================================================

class MockSQLConnector:
    """DataFrame-backed shim pra rodar local sem SQL Server."""
    _COLS_META = ["series_id", "country", "subject", "indicator",
                  "series_name", "data_type", "frequency", "description",
                  "haver_code", "bls_code"]
    _COLS_DATA = ["date", "series_id", "value", "release_date", "vintage_date"]

    def __init__(self):
        self.tables = {
            "OPT_Macro_Series_2":      pd.DataFrame(columns=self._COLS_META),
            "OPT_Macro_Series_Data_2": pd.DataFrame(columns=self._COLS_DATA),
        }
        self._next_id = 1
        self.conn = self  # pandas.read_sql aceita conn arbitraria via callback

    def execute(self, sql: str, params=None):
        # Trata DELETE FROM Data_2 (full ou incremental por date >= ?)
        sql_up = " ".join(sql.split()).upper()
        if "DELETE FROM OPT_MACRO_SERIES_DATA_2" in sql_up and params:
            t = self.tables["OPT_Macro_Series_Data_2"]
            if "AND DATE >= ?" in sql_up:
                sid, cutoff = params
                cutoff_ts = pd.Timestamp(cutoff)
                keep = ~((t.series_id == sid) & (pd.to_datetime(t.date) >= cutoff_ts))
                self.tables["OPT_Macro_Series_Data_2"] = t[keep].reset_index(drop=True)
            else:
                sid = params[0]
                self.tables["OPT_Macro_Series_Data_2"] = t[t.series_id != sid].reset_index(drop=True)

    def write_sql_table_from_dataframe(self, table: str, df: pd.DataFrame, chunk_size: int = 50):
        if table == "OPT_Macro_Series_2":
            df = df.copy()
            df["series_id"] = range(self._next_id, self._next_id + len(df))
            self._next_id += len(df)
            df = df.reindex(columns=self._COLS_META)
        base = self.tables[table]
        self.tables[table] = df.copy() if base.empty else pd.concat([base, df], ignore_index=True)

    def close(self):
        pass


def _read_sql_mock(sql: str, conn, params=None):
    """Handler pra pandas.read_sql chamado com MockSQLConnector."""
    sql_up = " ".join(sql.split()).upper()
    if "FROM OPT_MACRO_SERIES_2" in sql_up and "SERIES_ID" in sql_up:
        t = conn.tables["OPT_Macro_Series_2"]
        c, s, i, sn, dt = params
        m = ((t.country == c) & (t.subject == s) & (t.indicator == i)
             & (t.series_name == sn) & (t.data_type == dt))
        return t.loc[m, ["series_id"]].reset_index(drop=True)
    if "FROM OPT_MACRO_SERIES_DATA_2" in sql_up:
        # Check pra decidir seed vs incremental
        t = conn.tables["OPT_Macro_Series_Data_2"]
        sid = params[0]
        matched = t[t.series_id == sid]
        return matched.head(1)[["date"]] if not matched.empty else pd.DataFrame(columns=["date"])
    return pd.DataFrame()


# Monkey-patch: pandas.read_sql redireciona pro mock quando conn eh MockSQLConnector
_ORIG_READ_SQL = pd.read_sql
def _patched_read_sql(sql, con, *args, **kwargs):
    if isinstance(con, MockSQLConnector):
        return _read_sql_mock(sql, con, kwargs.get("params") or (args[0] if args else None))
    return _ORIG_READ_SQL(sql, con, *args, **kwargs)


# ============================================================================
# MAIN
# ============================================================================

def check_ri_freshness(idx_max_date: pd.Timestamp) -> None:
    """[WARN] se RI_BASE_DATE > 12 meses atras em relacao ao ultimo idx."""
    base = pd.Timestamp(RI_BASE_DATE + "-01")
    gap_months = (idx_max_date.year - base.year) * 12 + (idx_max_date.month - base.month)
    log(f"RI_BASE_DATE = {RI_BASE_DATE}  |  ultimo mes idx BLS = {idx_max_date:%Y-%m}")
    if gap_months > 12:
        log(f"[WARN] RI_BASE_DATE esta {gap_months} meses atras. Se BLS ja publicou "
            f"novo release (~fev/{idx_max_date.year}), atualize RI_BASE_DATE + "
            f"RI_HISTORICAL[{idx_max_date.year - 1}] no update_cpius_lean.py.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--cats", type=str, default=None,
                   help="Lista CSV de cats (ex: 'core_goods,oer').")
    p.add_argument("--codes", type=str, default=None,
                   help="Lista CSV de bls_codes (ex: 'CPIUS:core_goods,CPIUS:oer').")
    p.add_argument("--api-key", type=str, default=os.environ.get("BLS_API_KEY"),
                   help="Chave BLS API v2 (env BLS_API_KEY tb aceita).")
    p.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    p.add_argument("--end-year", type=int, default=DEFAULT_END_YEAR)
    p.add_argument("--simulate", action="store_true",
                   help="Nao conecta no SQL corp; usa MockSQLConnector local.")
    args = p.parse_args()

    requested_cats = parse_input(args.cats, args.codes)
    base_req = requested_cats & set(ITEM_CODES.keys())
    custom_req = requested_cats & set(CUSTOM_RECIPES.keys())
    log(f"cats pedidas: {len(base_req)} base + {len(custom_req)} custom "
        f"= {len(requested_cats)}: {sorted(requested_cats)}")

    # Fetch precisa cobrir base pedidas + deps das customs + TOP3 (renormalizacao Weight)
    fetch_cats = base_req | custom_deps(custom_req) | set(TOP3)
    if custom_req:
        log(f"custom deps adicionadas ao fetch: "
            f"{sorted(custom_deps(custom_req) - base_req)}")
    ids, id_map = build_series_ids(fetch_cats)
    raw = fetch_bls_batched(ids, args.start_year, args.end_year, args.api_key)

    # Reagrupa em wide por (cat, sa)
    log(f"reagrupando idx em wide (NSA/SA) e rebasando jan/2000=100...")
    idx_wide: dict[str, pd.DataFrame] = {}  # sa_flag -> wide (index=date, cols=cat)
    for sid, s in raw.items():
        cat, sa = id_map[sid]
        idx_wide.setdefault(sa, {})
        idx_wide[sa][cat] = rebase_jan2000(s)
    idx_nsa = pd.DataFrame(idx_wide.get("NSA", {})).sort_index()
    idx_sa  = pd.DataFrame(idx_wide.get("SA",  {})).sort_index()
    log(f"  NSA wide: {idx_nsa.shape[0]} meses x {idx_nsa.shape[1]} cats  |  "
        f"SA wide: {idx_sa.shape[0]} x {idx_sa.shape[1]}")

    if idx_nsa.empty:
        sys.exit("[ERR] BLS nao retornou dados NSA — abortando.")

    check_ri_freshness(idx_nsa.index.max())

    # Weight (usa NSA pra evitar poluicao por revisoes SA anuais). Computa pra
    # TODAS as fetch_cats — customs usam peso_wide como input do Dez-anchor.
    t_w = time.monotonic()
    log(f"computando Weight (ajuste implicito BLS) sobre {len(idx_nsa)} meses x "
        f"{len(idx_nsa.columns)} cats...")
    weights = compute_weights(idx_nsa, fetch_cats)
    log(f"  weights: {len(weights)} linhas em {time.monotonic()-t_w:.1f}s")

    # Constroi idx + Weight das customs pedidas e injeta em idx_nsa/idx_sa/weights
    if custom_req:
        t_c = time.monotonic()
        peso_wide = weights.pivot_table(index="date", columns="cat",
                                        values="weight").sort_index()
        log(f"construindo {len(custom_req)} customs via Laspeyres Dez-anchor...")
        for cc in sorted(custom_req):
            r = CUSTOM_RECIPES[cc]
            idx_nsa[cc] = build_custom_idx(r, idx_nsa, peso_wide)
            idx_sa[cc]  = build_custom_idx(r, idx_sa,  peso_wide)
            ws = build_custom_weight(r, peso_wide)
            if not ws.empty:
                weights = pd.concat([
                    weights,
                    pd.DataFrame({"date": ws.index, "cat": cc, "weight": ws.values}),
                ], ignore_index=True)
        log(f"  customs em {time.monotonic()-t_c:.1f}s")

    # Conecta SQL
    if args.simulate:
        session = MockSQLConnector()
        pd.read_sql = _patched_read_sql
        log("MODO SIMULATE — sem SQL real")
    else:
        log("conectando SQL corp (opt_utils.database.SQLConnector pyodbc)...")
        try:
            from opt_utils.database import SQLConnector  # type: ignore
        except ImportError:
            sys.exit("[ERR] opt_utils.database nao disponivel. Rode em corp OU use --simulate.")
        t_sql = time.monotonic()
        session = SQLConnector(connector="pyodbc")
        log(f"  SQL conectado em {time.monotonic()-t_sql:.1f}s")

    all_labels = {**CATEGORY_LABELS, **CUSTOM_LABELS}
    try:
        n_cats = len(requested_cats)
        for i, cat in enumerate(sorted(requested_cats), start=1):
            label = all_labels[cat]
            bls_code = CODE_FMT.format(cat=cat)
            is_custom = cat in CUSTOM_RECIPES
            bls_def = CATEGORY_BLS_DEFS.get(cat)
            def_suffix = f" - {bls_def}" if bls_def else ""
            src_desc = ("custom aggregation (Laspeyres Dez-anchor algebra)"
                        if is_custom else "BLS API v2 direto (lean)")
            tag = "[CUSTOM]" if is_custom else ""
            log(f"[{i}/{n_cats}] {cat} {tag} ({label})")
            t_cat = time.monotonic()

            for sa, wide in (("NSA", idx_nsa), ("SA", idx_sa)):
                if cat not in wide.columns:
                    log(f"    [{sa}] SKIP (sem dados)")
                    continue
                s = wide[cat].dropna()
                if s.empty:
                    log(f"    [{sa}] SKIP (serie vazia)")
                    continue
                log(f"    [{sa}] idx = {len(s)} obs "
                    f"{s.index.min():%Y-%m} -> {s.index.max():%Y-%m}, upserting...")
                upsert_series(
                    session, "US", "Prices", "CPI",
                    f"{label} (Index)", sa, "M",
                    f"{label} - Indice [{sa}] (rebased jan/2000=100){def_suffix} - {src_desc}",
                    bls_code, s,
                )

            w_series = weights[weights.cat == cat].set_index("date").weight.sort_index()
            if not w_series.empty:
                w_desc = (f"{label} - Weight (custom aggregation, derivado dos pesos base)"
                          if is_custom else
                          f"{label} - Weight (Relative Importance BLS, ajuste implicito, base {RI_BASE_DATE})")
                log(f"    [Weight] {len(w_series)} obs "
                    f"{w_series.index.min():%Y-%m} -> {w_series.index.max():%Y-%m}, upserting...")
                upsert_series(
                    session, "US", "Prices", "CPI",
                    f"{label} (Index)", "Weight", "M",
                    f"{w_desc}{def_suffix}",
                    bls_code, w_series,
                )
            else:
                log(f"    [Weight] SKIP (sem peso pra '{cat}')")
            log(f"    cat done in {time.monotonic()-t_cat:.1f}s")
    finally:
        log("fechando session SQL...")
        session.close()

    cats_with_weight = set(weights["cat"].unique()) if not weights.empty else set()
    n_no_weight = len(requested_cats - cats_with_weight)
    log(f"[OK] {len(requested_cats)} cats ({len(base_req)} base + {len(custom_req)} custom): "
        f"2 idx + Weight (Weight skipped em {n_no_weight}).")

    if args.simulate:
        meta = session.tables["OPT_Macro_Series_2"]
        data = session.tables["OPT_Macro_Series_Data_2"]
        log(f"[simulate] OPT_Macro_Series_2      = {len(meta)} rows")
        log(f"[simulate] OPT_Macro_Series_Data_2 = {len(data)} rows")
        print(meta[["series_id", "series_name", "data_type", "bls_code"]].to_string(index=False))


if __name__ == "__main__":
    main()
