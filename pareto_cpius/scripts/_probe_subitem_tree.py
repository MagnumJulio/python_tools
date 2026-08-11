#!/usr/bin/env python3
# Por que: valida se a arvore Table 1 (2020+) do RI subitem CSV
# gera descendants coerentes pros agregados chave (SAF1 food, SA0E energy,
# SA0L1E core, SASLE core_services). Prova de conceito Fase 2.
import csv
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
SUBITEM_CSV = ROOT / "data" / "cpi_cpius_pesos_annual_subitem.csv"
CU_ITEM = ROOT / "scripts" / "bls_maps" / "cu.item.tsv"


def load_year(year=2024):
    rows = []
    for r in csv.DictReader(open(SUBITEM_CSV, encoding="utf-8")):
        if int(r["year"]) == year:
            rows.append({
                "indent": int(r["indent"]),
                "code": r["item_code"],
                "name": r["item_name"],
                "cpi_u": float(r["cpi_u"]),
            })
    return rows


def build_parents(rows):
    """A partir do indent, atribui parent_code = ultimo item visto com indent < atual."""
    # rows sao lidos na ordem do CSV (que reflete ordem do RI file = ordem hierarquica)
    stack = []  # (indent, code)
    for r in rows:
        while stack and stack[-1][0] >= r["indent"]:
            stack.pop()
        r["parent"] = stack[-1][1] if stack else None
        stack.append((r["indent"], r["code"]))
    return rows


def descendants(rows, root_code):
    """BFS: retorna set de codes descendentes (incluindo root)."""
    kids_of = defaultdict(list)
    for r in rows:
        if r["parent"]:
            kids_of[r["parent"]].append(r["code"])
    out = set([root_code])
    stack = [root_code]
    while stack:
        cur = stack.pop()
        for k in kids_of.get(cur, []):
            if k not in out:
                out.add(k)
                stack.append(k)
    return out


def leaves(rows, subset_codes):
    """Retorna subset ∩ folhas (sem filhos)."""
    kids_of = defaultdict(list)
    for r in rows:
        if r["parent"]:
            kids_of[r["parent"]].append(r["code"])
    return {c for c in subset_codes if not kids_of.get(c)}


def sum_weight(rows, codes):
    code_to_w = {r["code"]: r["cpi_u"] for r in rows}
    return sum(code_to_w.get(c, 0) for c in codes)


def main():
    rows = build_parents(load_year(2024))
    print(f"Year 2024: {len(rows)} rows")
    print(f"First 5 with parent:")
    for r in rows[:5]:
        print(f"  {r['indent']} {r['code']} <- parent={r['parent']} | {r['name']} | w={r['cpi_u']}")

    # Sanity: All items weight = 100
    all_items_code = "SA0"
    print(f"\nSA0 (All items): weight in file = {sum_weight(rows, [all_items_code]):.3f}")

    # Descendants of key aggregates
    for agg_name, code in [
        ("all_items", "SA0"),
        ("food", "SAF1"),
        ("energy", "SA0E"),
        ("shelter", "SAH1"),
        ("core_services", "SASLE"),
        ("medical_care", "SAM"),
    ]:
        desc = descendants(rows, code)
        lvs = leaves(rows, desc)
        w_desc = sum_weight(rows, desc) - sum_weight(rows, [code])  # exclui root
        w_lvs = sum_weight(rows, lvs)
        print(f"\n  {agg_name} ({code}): descendants={len(desc)}, leaves={len(lvs)}")
        print(f"     weight(root)={sum_weight(rows, [code]):.3f}, weight(leaves)={w_lvs:.3f}")

    # For core (SA0L1E) — not in Table 1 tree
    print(f"\n  core (SA0L1E) — SPECIAL AGGREGATE, not in main tree")
    if "SA0L1E" in {r['code'] for r in rows}:
        print("     found in RI data as separate row")
    else:
        print("     NOT found — must be computed via exclusion algebra")
        # Compute: descendants(SA0) - descendants(SAF1) - descendants(SA0E)
        exc = descendants(rows, "SAF1") | descendants(rows, "SA0E")
        core_subs = descendants(rows, "SA0") - exc
        core_leaves = leaves(rows, core_subs)
        w = sum_weight(rows, core_leaves)
        print(f"     via algebra: leaves={len(core_leaves)}, weight={w:.3f}")


if __name__ == "__main__":
    main()
