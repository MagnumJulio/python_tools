# Alternative Core Inflation Measures — CPI-U + PCE

Medidas de inflação subjacente alternativas pra servir ao gestor de fundo.
Fonte primária: dados **oficiais Fed** (match 100%). Custom bottom-up só
para medidas que não existem oficial.

## Deliverables

### CPI-U — `pareto_cpius/data/cpi_cpius_alt_measures.csv`

Long schema: `date, measure, ann_1mo, ann_12mo`.

| Measure | Fonte | ann_1mo | ann_12mo | Janela |
|---|---|---|---|---|
| `sticky_cpi` | Atlanta Fed xlsx oficial | ✓ | ✓ | 1967-01 → atual |
| `core_sticky_cpi` | Atlanta Fed xlsx oficial | ✓ | ✓ | 1967-01 → atual |
| `flexible_cpi` | Atlanta Fed xlsx oficial | ✓ | ✓ | 1967-01 → atual |
| `core_flexible_cpi` | Atlanta Fed xlsx oficial | ✓ | ✓ | 1967-01 → atual |
| `sticky_cpi_ex_shelter` | Atlanta Fed xlsx oficial | ✓ | ✓ | 1967-01 → atual |
| `core_sticky_cpi_ex_shelter` | Atlanta Fed xlsx oficial | ✓ | ✓ | 1967-01 → atual |
| `median_cpi` | FRED `MEDCPIM158SFRBCLE` (Cleveland) | ✓ (via FRED) | — | 1983-01 → atual |
| `trimmed_mean_16_cpi` | FRED `TRMMEANCPIM158SFRBCLE` (Cleveland) | ✓ (via FRED) | — | 1983-01 → atual |
| `trimmed_sym_25_cpi_custom` | **Bottom-up próprio** (universe indent-3 BLS) | ✓ | — | 2001-01 → atual |

Fallback Cleveland chartdata CSV (YoY, 2017+) é usado automaticamente quando
FRED não responde.

### PCE — `pareto_pce/data/pce_alt_measures.csv`

Long schema: `date, measure, ann_1mo, ann_12mo`.

| Measure | Fonte | ann_1mo | ann_12mo | Janela |
|---|---|---|---|---|
| `median_pce` | Cleveland Fed CSV oficial | ✓ | ✓ | 1977-01 → atual |
| `trimmed_mean_pce_1mo` | FRED `PCETRIM1M680SFRBDAL` (Dallas) | ✓ | — | 1977-01 → atual (via FRED) |
| `trimmed_mean_pce_12mo` | FRED `PCETRIM12M680SFRBDAL` (Dallas) | — | ✓ | 1977-01 → atual (via FRED) |

## Como rodar

### Fetch (local ou corp)

```bash
# CPI
cd pareto_cpius
python scripts/build_alt_measures_cpi.py             # NSA + Atlanta + custom
python scripts/build_alt_measures_cpi.py --help      # opções
#   SKIP_CUSTOM=1    pula o Trimmed Sym 25% (so entrega oficial)
#   FORCE_FETCH=1    re-baixa BLS subitem (invalida cache)

# PCE
cd pareto_pce
python scripts/build_alt_measures_pce.py
```

### Dependências de rede

| Fonte | Primary endpoint | Fallback |
|---|---|---|
| Atlanta Fed | `atlantafed.org/.../stickprice.xlsx` | — |
| Cleveland CPI chart | `clevelandfed.org/.../mediancpi/mediancpi_chartdata.csv` | — |
| Cleveland PCE full | `clevelandfed.org/.../medianpce/median-pce-full-history.csv` | — |
| **FRED (Cleveland + Dallas full series)** | `fred.stlouisfed.org/graph/fredgraph.csv?id=X` | — |
| BLS (custom bottom-up) | `api.bls.gov/publicAPI/v2/timeseries/data/` | NSA fallback (CUUR) |

**FRED pode ter edge temporariamente lento/bloqueado em algumas redes.** Os
scripts retry 3× com backoff; se falhar, segue com fallback (Cleveland
chartdata para CPI) ou pula (Dallas PCE — vai aparecer vazio).

### Load SQL corp

```bash
# CPI
python pareto_cpius/script_itau/load_alt_measures_cpi_to_sql.py --dry-run
python pareto_cpius/script_itau/load_alt_measures_cpi_to_sql.py

# PCE
python pareto_pce/script_itau/load_alt_measures_pce_to_sql.py --dry-run
python pareto_pce/script_itau/load_alt_measures_pce_to_sql.py
```

Flags disponíveis em ambos:
- `--dry-run`: lista o que faria, não escreve
- `--no-confirm`: pula prompt interativo
- `--full`: carga full history (default: últimos 24 meses)
- `--only measure1,measure2`: só algumas measures

## Schema SQL (corp)

Cada measure vira 1-2 séries no `OPT_Macro_Series_2`:
- `country`: US
- `subject`: Prices
- `indicator`: CPI (para CPI-U alt) ou PCE (para PCE alt)
- `data_type`: NSA
- `frequency`: M
- `series_name`: ex. `"CPI-U: Core Sticky-Price (Atlanta Fed) [1-mo annualized]"`
- `bls_code`: ex. `"CPIUS:alt_core_sticky_cpi_1mo"` / `"PCE:alt_median_pce_12mo"`
- `haver_code`: NULL (sync 2026-07-20 pattern)

Namespace `alt_` disjunto das séries base IPCA/CPI/PCE existentes.

## Status das medidas (snapshot delivery)

Rodado em casa (sem corp proxy). FRED timeout em algumas, Atlanta/Cleveland OK:

```
Atlanta Fed 6 series:                 ✓ 715 obs cada (1967-2026)
Custom Trimmed Sym 25%:               ✓ 307 obs (2001-2026)
Cleveland Median PCE:                 ✓ 595 obs (1977-2026)
FRED Cleveland Median CPI:            ⚠ fetch falhou local (vai do corp)
FRED Cleveland Trimmed Mean CPI:      ⚠ fetch falhou local (vai do corp)
FRED Dallas Trimmed Mean PCE 1mo:     ⚠ fetch falhou local (vai do corp)
FRED Dallas Trimmed Mean PCE 12mo:    ⚠ fetch falhou local (vai do corp)
```

**Pra completar o delivery no corp**: rodar `build_alt_measures_cpi.py` e
`build_alt_measures_pce.py` com `CORP_PROXY_URL` setado. Depois load SQL
normal.
