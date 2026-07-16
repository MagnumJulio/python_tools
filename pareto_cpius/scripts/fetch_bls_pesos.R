#!/usr/bin/env Rscript
# fetch_bls_pesos.R
#
# Gera data/cpi_cpius_pesos.csv com pesos VARIAVEIS NO TEMPO (Fase 2 BLS).
#
# Fonte: data/cpi_cpius_pesos_annual.csv (parsed a partir das releases Table 6
# de Dezembro 2000-2025 em data/raw/relative_importance/, via
# scripts/parse_historical_ri.py).
#
# Metodologia (fiel ao BLS): pra cada mes m no ano fiscal Jan(t) -> Dez(t),
# usa base Dez(t-1) e aplica ajuste implicito de preco:
#
#   w_i(m) = w_i(Dez_{t-1}) * I_i(m) / I_i(Dez_{t-1})
#
# depois renormaliza pros pesos de cada nivel-1 (food, energy, core) somarem
# ao valor top-1 esperado (mantém coerencia hierarquica). Aqui simplificamos
# renormalizando a soma dos 3 top-1 pra 100.
#
# Isso implementa o que BLS chama de "monthly relative importance" — os
# pesos publicados em Dez sao pesos BASE (base_period=Dec), e o BLS ajusta
# monthly reponderando por preco. Ver:
# https://www.bls.gov/cpi/technical-notes/#relimport
#
# Uso:
#   cd pareto_cpius
#   python scripts/parse_historical_ri.py         # gera pesos_annual.csv
#   Rscript scripts/fetch_bls_cpiu.R              # gera cpi_cpius_recon.csv
#   Rscript scripts/fetch_bls_pesos.R             # este script
#
# Saida:
#   data/cpi_cpius_pesos.csv - long (date, category_code, value)

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

ANNUAL_CSV <- "data/cpi_cpius_pesos_annual.csv"
RECON_CSV  <- "data/cpi_cpius_recon.csv"
MAP_CSV    <- "scripts/bls_maps/cpiu_table_1.csv"
OUT_CSV    <- "data/cpi_cpius_pesos.csv"

if (!file.exists(ANNUAL_CSV))
  stop(sprintf("Pesos anuais nao encontrados: %s (rode parse_historical_ri.py antes)", ANNUAL_CSV))
if (!file.exists(RECON_CSV))
  stop(sprintf("Recon nao encontrado: %s (rode fetch_bls_cpiu.R antes)", RECON_CSV))
if (!file.exists(MAP_CSV))
  stop(sprintf("Mapa canonico nao encontrado: %s", MAP_CSV))

annual <- read.csv(ANNUAL_CSV, stringsAsFactors = FALSE)
recon  <- read.csv(RECON_CSV,  stringsAsFactors = FALSE)
smap   <- read.csv(MAP_CSV,    stringsAsFactors = FALSE, encoding = "UTF-8")

recon$date <- as.Date(recon$date)
# Por que: usar NSA como referencia de preco pro ajuste implicito
# (evita revisoes SA anuais poluirem o peso historico).
recon <- recon[recon$sa_flag == "NSA", ]

cats <- smap$category_code
n_cats <- length(cats)
cat(sprintf("[1] %d categorias, %d anos-base (%d-%d)\n",
            n_cats, length(unique(annual$year)),
            min(annual$year), max(annual$year)))

# Datas: calendar universal do recon (mensal, jan/2000 → atual)
datas <- sort(unique(recon$date[recon$category_code == "all_items"]))
cat(sprintf("[2] %d datas: %s → %s\n",
            length(datas), format(min(datas)), format(max(datas))))

# --- Ajuste implicito de peso ---
# Pra cada data m (mes fiscal do ano t): base_year = t-1.
# w_i(m) = w_i(Dez_{base_year}) * I_i(m) / I_i(Dez_{base_year})
# depois renormaliza sum(w_food + w_energy + w_core) == 100.

# Constroi wide: index por (date, category_code)
idx_wide <- reshape(recon[, c("date","category_code","value_index")],
                    idvar = "date", timevar = "category_code", direction = "wide")
names(idx_wide) <- sub("^value_index\\.", "", names(idx_wide))
rownames(idx_wide) <- format(idx_wide$date)
idx_mat <- as.matrix(idx_wide[, cats])
storage.mode(idx_mat) <- "numeric"

# Pesos base por ano: (year, category_code) → RI
base_ri <- reshape(annual[, c("year","category_code","relative_importance")],
                   idvar = "year", timevar = "category_code", direction = "wide")
names(base_ri) <- sub("^relative_importance\\.", "", names(base_ri))
rownames(base_ri) <- as.character(base_ri$year)
# alinha colunas com cats (algumas categorias podem faltar em anos historicos)
missing_hist <- setdiff(cats, names(base_ri))
if (length(missing_hist)) {
  cat(sprintf("[WARN] Categorias sem base historica: %s (usarao base do ano seguinte)\n",
              paste(missing_hist, collapse=",")))
}
for (c in missing_hist) base_ri[[c]] <- NA_real_
ri_mat <- as.matrix(base_ri[, cats])
storage.mode(ri_mat) <- "numeric"

# Por que: pra cada mes, escolhe base_year = year(date)-1 (peso publicado em
# Dez do ano anterior). Excecao: pra meses do ano y=min(annual$year) (2000)
# e do primeiro ano com dados mas sem base disponivel, usa o proprio ano
# como fallback (peso vigente na epoca).
anos_base <- as.integer(rownames(ri_mat))
choose_base <- function(m_date) {
  y <- as.integer(format(m_date, "%Y"))
  cand <- y - 1L
  if (cand %in% anos_base) return(cand)
  # fallback: primeiro ano disponivel >= y (ou ultimo <= y-1)
  le <- anos_base[anos_base <= y]
  if (length(le)) return(max(le))
  return(min(anos_base))
}

# Data de referencia do peso base: dez do ano base.
# Ex.: base_year=2019 → I_i(2019-12-01)
peso_out <- vector("list", length(datas))
for (k in seq_along(datas)) {
  m <- datas[k]
  base_y <- choose_base(m)
  # linha do RI base
  ri_row <- ri_mat[as.character(base_y), ]
  # linha do indice em Dez(base_y). Fallback: se falta (edge: dez do ultimo
  # ano ainda nao publicado), usa o proprio mes m como referencia (nao muda).
  dez_key <- format(as.Date(sprintf("%d-12-01", base_y)))
  idx_dez <- if (dez_key %in% rownames(idx_mat)) idx_mat[dez_key, ] else idx_mat[format(m), ]
  idx_m   <- idx_mat[format(m), ]
  # ajuste implicito. Por que: quando I_i(m) esta NA (gap na Table 1 BLS,
  # e.g. hospital_services 2022-10), cai pro peso base sem ajuste.
  ratio <- idx_m / idx_dez
  ratio[!is.finite(ratio)] <- 1
  w <- ri_row * ratio
  # renormaliza pros 3 top-1 (food+energy+core) somarem 100
  top3 <- c("food","energy","core")
  s3 <- sum(w[top3], na.rm = TRUE)
  if (is.finite(s3) && s3 > 0) w <- w * (100 / s3)
  peso_out[[k]] <- w
}

M <- do.call(rbind, peso_out)
rownames(M) <- format(datas)

# Long
out <- data.frame(date = rep(datas, each = n_cats),
                  category_code = rep(cats, times = length(datas)),
                  value = as.vector(t(M)),
                  stringsAsFactors = FALSE)
out$value <- round(out$value, 4)

dir.create("data", showWarnings = FALSE, recursive = TRUE)
write.csv(out, OUT_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("[3] %d linhas -> %s\n", nrow(out), OUT_CSV))

# ---- Sanity ----
d0 <- min(datas); d1 <- max(datas)
for (dd in c(d0, as.Date("2010-06-01"), as.Date("2020-06-01"), d1)) {
  if (!(format(dd) %in% rownames(M))) next
  row <- M[format(dd), ]
  s3 <- sum(row[c("food","energy","core")], na.rm = TRUE)
  cat(sprintf("[Sanity] %s food+energy+core = %.3f  (all_items=%.3f)\n",
              format(dd), s3, row["all_items"]))
}

# Amostra: variacao do peso de gasoline ao longo do tempo
cat("\n[Sample] peso gasoline em datas selecionadas:\n")
for (dd in c(as.Date("2000-06-01"), as.Date("2008-06-01"), as.Date("2015-12-01"),
             as.Date("2020-04-01"), as.Date("2022-06-01"), d1)) {
  if (!(format(dd) %in% rownames(M))) next
  cat(sprintf("  %s  gasoline=%.3f  oer=%.3f  shelter=%.3f  airline=%.3f\n",
              format(dd), M[format(dd),"gasoline"], M[format(dd),"oer"],
              M[format(dd),"shelter"], M[format(dd),"airline_fares"]))
}
cat("OK.\n")
