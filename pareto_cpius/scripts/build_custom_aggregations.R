#!/usr/bin/env Rscript
# build_custom_aggregations.R
#
# Constroi agregacoes CPI-U customizadas (core ex OER, super super core,
# supercore-Powell, etc.) via algebra Laspeyres com os pesos mensais que ja
# temos (data/cpi_cpius_pesos.csv) e os indices NSA+SA (data/cpi_cpius_recon.csv).
#
# Recipe file: scripts/bls_maps/custom_aggregations.csv com colunas:
#   code, label, method, base, excludes, includes, description
#
# Methods:
#   exclude: var_agg(m) = (var_base × w_base - Σ var_i × w_i) / (w_base - Σ w_i)
#            (i em excludes; requer que excludes sejam subconjunto nao-sobreposto do base)
#   sum:     var_agg(m) = Σ var_i × w_i / Σ w_i
#            (i em includes; usado quando nao existe agregado BLS pronto)
#
# Algebra (2026-07-21) — Laspeyres modificado Dez-anchor (BLS canonico):
# Para cada mes m, pivot = Dez do ano anterior. Fallback jan/2000 pra 2000.
# Formula:
#   ratio_i(m)  = I_i(m) / I_i(pivot)
#   ratio_ex(m) = [W_base*ratio_base - Sum w_i*ratio_i] / [W_base - Sum w_i]
#   I_ex(m)     = I_ex(pivot) * ratio_ex(m)
# Pesos e indices no pivot vem de cpi_cpius_pesos.csv e cpi_cpius_recon.csv.
# Var mm derivada do chain de indices reconstruidos.
# Peso servido (OUT_PESOS_CSV) continua mensal ajustado — reflete peso
# corrente do agregado no consumo; nao muda com o refactor.
# Motivacao: substitui algebra antiga (var-nivel c/ peso mensal), que
# acumulava erro conforme # excludes crescia. Ver memory project_pareto_cpius_customs_laspeyres_test.md
#
# Saida:
#   data/cpi_cpius_custom.csv  — mesmo schema do recon (long: date,
#     category_code, sa_flag, series_id=NA, value_index, value_var_mm, value_var_yoy)
#
# Uso:
#   cd pareto_cpius
#   Rscript scripts/build_custom_aggregations.R

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

RECON_CSV     <- "data/cpi_cpius_recon.csv"
PESOS_CSV     <- "data/cpi_cpius_pesos.csv"
RECIPE_CSV    <- "scripts/bls_maps/custom_aggregations.csv"
OUT_CSV       <- "data/cpi_cpius_custom.csv"
OUT_PESOS_CSV <- "data/cpi_cpius_pesos_custom.csv"

if (!file.exists(RECON_CSV))  stop(sprintf("Nao encontrei %s", RECON_CSV))
if (!file.exists(PESOS_CSV))  stop(sprintf("Nao encontrei %s", PESOS_CSV))
if (!file.exists(RECIPE_CSV)) stop(sprintf("Nao encontrei %s", RECIPE_CSV))

recon <- read.csv(RECON_CSV, stringsAsFactors = FALSE)
pesos <- read.csv(PESOS_CSV, stringsAsFactors = FALSE)
recipe <- read.csv(RECIPE_CSV, stringsAsFactors = FALSE)

recon$date <- as.Date(recon$date)
pesos$date <- as.Date(pesos$date)

# Split de excludes/includes (;-separado)
split_list <- function(s) {
  if (is.na(s) || !nzchar(s)) return(character(0))
  trimws(strsplit(s, ";", fixed = TRUE)[[1]])
}

cat(sprintf("[1] %d recipes carregadas\n", nrow(recipe)))

# Loop por sa_flag (NSA e SA)
sa_flags <- unique(recon$sa_flag)
datas <- sort(unique(recon$date))
cat(sprintf("[2] %d datas x %d sa_flags\n", length(datas), length(sa_flags)))

# Pre-cache: wide matrices por sa_flag
# var[date, cat] e peso[date, cat]
var_wide <- list()
idx_wide <- list()
for (sf in sa_flags) {
  sub <- recon[recon$sa_flag == sf, c("date","category_code","value_var_mm","value_index")]
  w_var <- reshape(sub[, c("date","category_code","value_var_mm")],
                   idvar = "date", timevar = "category_code", direction = "wide")
  names(w_var) <- sub("^value_var_mm\\.", "", names(w_var))
  rownames(w_var) <- format(w_var$date)
  w_idx <- reshape(sub[, c("date","category_code","value_index")],
                   idvar = "date", timevar = "category_code", direction = "wide")
  names(w_idx) <- sub("^value_index\\.", "", names(w_idx))
  rownames(w_idx) <- format(w_idx$date)
  var_wide[[sf]] <- w_var
  idx_wide[[sf]] <- w_idx
}

# Peso wide
w_peso <- reshape(pesos, idvar = "date", timevar = "category_code", direction = "wide")
names(w_peso) <- sub("^value\\.", "", names(w_peso))
rownames(w_peso) <- format(w_peso$date)

# Constroi cada recipe
out_rows <- vector("list", 0)
peso_rows <- vector("list", 0)

for (ri in seq_len(nrow(recipe))) {
  r <- recipe[ri, ]
  method <- r$method
  base_cat <- if (is.na(r$base) || !nzchar(r$base)) NA else r$base
  excl <- split_list(r$excludes)
  incl <- split_list(r$includes)
  code <- r$code
  cat(sprintf("  [%s] method=%s base=%s excl=%s incl=%s\n",
              code, method,
              if (is.na(base_cat)) "-" else base_cat,
              paste(excl, collapse=","),
              paste(incl, collapse=",")))

  for (sf in sa_flags) {
    iw <- idx_wide[[sf]]

    idx_series  <- rep(NA_real_, length(datas))
    peso_series <- rep(NA_real_, length(datas))
    idx_series[1] <- 100  # jan/2000 = 100 (rebase)

    for (k in seq_along(datas)) {
      dk <- format(datas[k])
      if (!(dk %in% rownames(iw))) next
      if (!(dk %in% rownames(w_peso))) next

      wrow_m <- w_peso[dk, ]  # pesos mensais adjusted (pro OUT_PESOS_CSV)

      # === peso mensal do agregado (para SQL Weight) ===
      if (method == "exclude") {
        if (is.na(base_cat) || !(base_cat %in% names(wrow_m))) next
        w_base_m <- as.numeric(wrow_m[[base_cat]])
        p_num <- w_base_m; p_ok <- is.finite(w_base_m)
        for (e in excl) {
          if (!p_ok) break
          we <- as.numeric(wrow_m[[e]])
          if (!is.finite(we)) { p_ok <- FALSE; break }
          p_num <- p_num - we
        }
        if (p_ok && p_num > 0) peso_series[k] <- p_num
      } else if (method == "sum") {
        p_num <- 0; p_ok <- length(incl) > 0
        for (i in incl) {
          if (!p_ok) break
          wi <- as.numeric(wrow_m[[i]])
          if (!is.finite(wi)) { p_ok <- FALSE; break }
          p_num <- p_num + wi
        }
        if (p_ok && p_num > 0) peso_series[k] <- p_num
      } else {
        stop(sprintf("method desconhecido: %s", method))
      }

      # === indice via Laspeyres Dez-anchor ===
      if (k == 1) next  # idx_series[1] = 100 ja setado

      y  <- as.integer(format(datas[k], "%Y"))
      pd <- as.Date(sprintf("%d-12-01", y - 1))
      if (pd < datas[1]) pd <- datas[1]  # fallback jan/2000 pra ano 2000
      pdk <- format(pd)
      if (!(pdk %in% rownames(iw))) next
      if (!(pdk %in% rownames(w_peso))) next

      pk <- which(datas == pd)
      if (length(pk) == 0) next
      i_ex_pivot <- idx_series[pk]
      if (!is.finite(i_ex_pivot)) next

      irow_m <- iw[dk, ]
      irow_p <- iw[pdk, ]
      wrow_p <- w_peso[pdk, ]

      if (method == "exclude") {
        if (!(base_cat %in% names(irow_m))) next
        i_b_m <- as.numeric(irow_m[[base_cat]])
        i_b_p <- as.numeric(irow_p[[base_cat]])
        w_b_p <- as.numeric(wrow_p[[base_cat]])
        ok <- is.finite(i_b_m) && is.finite(i_b_p) && is.finite(w_b_p) && i_b_p > 0
        num <- w_b_p * (i_b_m / i_b_p)
        den <- w_b_p
        for (e in excl) {
          if (!ok) break
          i_e_m <- as.numeric(irow_m[[e]])
          i_e_p <- as.numeric(irow_p[[e]])
          w_e_p <- as.numeric(wrow_p[[e]])
          if (!is.finite(i_e_m) || !is.finite(i_e_p) || !is.finite(w_e_p) || i_e_p == 0) {
            ok <- FALSE; break
          }
          num <- num - w_e_p * (i_e_m / i_e_p)
          den <- den - w_e_p
        }
        if (ok && den > 0) idx_series[k] <- i_ex_pivot * (num / den)
      } else if (method == "sum") {
        num <- 0; den <- 0; ok <- length(incl) > 0
        for (i in incl) {
          if (!ok) break
          i_m <- as.numeric(irow_m[[i]])
          i_p <- as.numeric(irow_p[[i]])
          w_p <- as.numeric(wrow_p[[i]])
          if (!is.finite(i_m) || !is.finite(i_p) || !is.finite(w_p) || i_p == 0) {
            ok <- FALSE; break
          }
          num <- num + w_p * (i_m / i_p)
          den <- den + w_p
        }
        if (ok && den > 0) idx_series[k] <- i_ex_pivot * (num / den)
      }
    }

    # var mm derivado do chain de indices reconstruidos
    var_series <- rep(NA_real_, length(datas))
    for (k in 2:length(datas)) {
      if (is.finite(idx_series[k]) && is.finite(idx_series[k-1]) && idx_series[k-1] > 0) {
        var_series[k] <- (idx_series[k] / idx_series[k-1] - 1) * 100
      }
    }

    # yoy = idx(m) / idx(m-12) - 1
    yoy_series <- rep(NA_real_, length(datas))
    if (length(datas) > 12) {
      for (k in 13:length(datas)) {
        if (is.finite(idx_series[k]) && is.finite(idx_series[k-12]) && idx_series[k-12] > 0) {
          yoy_series[k] <- (idx_series[k] / idx_series[k-12] - 1) * 100
        }
      }
    }

    out_rows[[length(out_rows) + 1]] <- data.frame(
      date          = datas,
      category_code = code,
      sa_flag       = sf,
      series_id     = NA_character_,
      value_index   = round(idx_series, 6),
      value_var_mm  = round(var_series, 6),
      value_var_yoy = round(yoy_series, 6),
      stringsAsFactors = FALSE
    )

    # Pesos nao dependem de sa_flag — grava so uma vez por recipe
    if (sf == sa_flags[1]) {
      peso_rows[[length(peso_rows) + 1]] <- data.frame(
        date          = datas,
        category_code = code,
        value         = round(peso_series, 4),
        stringsAsFactors = FALSE
      )
    }
  }
}

out <- do.call(rbind, out_rows)
out <- out[order(out$date, out$category_code, out$sa_flag), ]

dir.create("data", showWarnings = FALSE, recursive = TRUE)

# Backup do output antigo (var-nivel) na primeira execucao pos-refactor
BACKUP_CSV <- sub("\\.csv$", ".pre_laspeyres_test.csv", OUT_CSV)
if (file.exists(OUT_CSV) && !file.exists(BACKUP_CSV)) {
  file.copy(OUT_CSV, BACKUP_CSV, overwrite = FALSE)
  cat(sprintf("[backup] %s -> %s\n", OUT_CSV, BACKUP_CSV))
}

write.csv(out, OUT_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("\n[3] %d linhas -> %s\n", nrow(out), OUT_CSV))

# Grava pesos custom (drop linhas com NA no value pra CSV mais limpo)
out_pesos <- do.call(rbind, peso_rows)
out_pesos <- out_pesos[!is.na(out_pesos$value), ]
out_pesos <- out_pesos[order(out_pesos$date, out_pesos$category_code), ]
write.csv(out_pesos, OUT_PESOS_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("[4] %d linhas -> %s\n", nrow(out_pesos), OUT_PESOS_CSV))

# Sanity: ultimo ponto NSA por recipe
cat("\n[Sanity] Ultimo ponto (NSA) por agregado:\n")
last_d <- max(out$date)
last <- out[out$date == last_d & out$sa_flag == "NSA", ]
last <- last[order(-abs(last$value_var_yoy)), ]
print(last[, c("category_code","date","value_index","value_var_mm","value_var_yoy")],
      row.names = FALSE, right = FALSE)
cat("\nOK.\n")
