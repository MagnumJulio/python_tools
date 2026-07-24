#!/usr/bin/env python3
# Por que: constroi arvore hierarquica (subitem -> aggregate) usando indent
# da RI Table 1. Aplica patches manuais pra anomalias BLS conhecidas
# (Alcoholic beverages no indent errado, etc.).
# Output: data/cpi_cpius_subitem_hierarchy.csv (year, code, parent, is_leaf)
# + valida sum(leaves under X) == weight(X) por agregado.
import csv
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "data" / "cpi_cpius_pesos_annual_subitem.csv"
OUT_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"

# Patches manuais: forcar parent_code pra items com indent enganoso na RI Table 1.
# Chave = item_code do filho, valor = codigo forcado como parent.
# BLS as vezes indenta visualmente sob um pai que nao eh o pai aggregacional.
PARENT_PATCH = {
    # SAF116 (Alcoholic beverages) aparece indent 3 sob Food (SAF1),
    # mas semanticamente eh sibling de SAF1 sob SAF (Food and beverages).
    # Verificacao: SAF1 (13.691) + SAF116 (0.835) = SAF (14.526) ✓
    "SAF116": "SAF",
}

# Codigos de agregados a validar sum(leaves) == root_weight.
# Nao inclui Special Aggregate Indexes (core, core_services) — esses sao
# reconstruidos algebraically no Phase 4.
VALIDATE_AGGS = [
    "SA0",       # All items
    "SAF",       # Food and beverages
    "SAF1",      # Food
    "SAF11",     # Food at home
    "SEFV",      # Food away from home
    "SAF116",    # Alcoholic beverages
    "SAH",       # Housing
    "SAH1",      # Shelter
    "SAA",       # Apparel
    "SAT",       # Transportation
    "SAM",       # Medical care
    "SAR",       # Recreation
    "SAE",       # Education and communication
    "SAG",       # Other goods and services
]


def build_tree(rows):
    """Rows na ordem do CSV. Aplica indent-stack + patches."""
    stack = []
    for r in rows:
        while stack and stack[-1][0] >= r["indent"]:
            stack.pop()
        r["parent"] = stack[-1][1] if stack else None
        # aplica patch
        if r["code"] in PARENT_PATCH:
            r["parent"] = PARENT_PATCH[r["code"]]
            # NAO empilha o item patched, pra evitar contaminar children subsequentes
            # Actually — precisamos empilhar com indent "correto"?
            # Simpler: empilha com indent atual (BLS's), assumindo que patches sao
            # para items SEM filhos abaixo (Alcoholic bev tem filhos SEFW, SEFX).
            # Vamos empilhar mas com indent que reflete parent forcado.
            # Estrategia: retire do stack tudo com indent >= r["indent"] (ja feito),
            # depois empilha com indent = r["indent"] mesmo (BLS keep).
        stack.append((r["indent"], r["code"]))
    return rows


def compute_by_year(all_rows, year):
    rows = [dict(r) for r in all_rows if r["year"] == year]
    build_tree(rows)
    kids = defaultdict(list)
    for r in rows:
        if r["parent"]:
            kids[r["parent"]].append(r["code"])
    by_code = {r["code"]: r for r in rows}

    def leaves_under(root):
        out = set()
        stk = [root]
        while stk:
            c = stk.pop()
            children = kids.get(c, [])
            if not children:
                out.add(c)
            for k in children:
                stk.append(k)
        return out

    return rows, kids, by_code, leaves_under


def main():
    all_rows = []
    for r in csv.DictReader(open(IN_CSV, encoding="utf-8")):
        all_rows.append({
            "year": int(r["year"]),
            "indent": int(r["indent"]),
            "code": r["item_code"],
            "name": r["item_name"],
            "weight": float(r["cpi_u"]),
        })

    years = sorted(set(r["year"] for r in all_rows))
    print(f"Years: {years[0]}-{years[-1]} ({len(years)} anos)")

    # Filtro pra 2020+ (option 3)
    all_rows = [r for r in all_rows if r["year"] >= 2020]
    years = sorted(set(r["year"] for r in all_rows))
    print(f"Filtro >=2020: {years}")

    # Valida por ano
    print(f"\n{'agg':<10} " + " ".join(f"{y:>7}" for y in years))
    for agg in VALIDATE_AGGS:
        print(f"{agg:<10}", end=" ")
        for year in years:
            rows, kids, by_code, leaves_under = compute_by_year(all_rows, year)
            if agg not in by_code:
                print(f"{'N/A':>7}", end=" ")
                continue
            root_w = by_code[agg]["weight"]
            lvs = leaves_under(agg)
            sum_l = sum(by_code[c]["weight"] for c in lvs)
            diff = sum_l - root_w
            mark = "" if abs(diff) < 0.05 else "*"
            print(f"{diff:+7.2f}{mark}", end="")
        print()

    # Escreve hierarquia + is_leaf por ano
    out_rows = []
    for year in years:
        rows, kids, by_code, _ = compute_by_year(all_rows, year)
        for r in rows:
            out_rows.append({
                "year": year,
                "item_code": r["code"],
                "item_name": r["name"],
                "parent_code": r["parent"] or "",
                "indent": r["indent"],
                "is_leaf": "1" if not kids.get(r["code"]) else "0",
                "cpi_u": f"{r['weight']:.4f}",
            })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["year", "item_code", "item_name",
                                           "parent_code", "indent", "is_leaf", "cpi_u"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n[out] {OUT_CSV}: {len(out_rows)} linhas")


if __name__ == "__main__":
    main()
