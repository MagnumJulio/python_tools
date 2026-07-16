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
# Ambos os metodos usam pesos MENSAIS ajustados (o mesmo do fetch_bls_pesos.R
# v2). Indices reconstruidos por composicao mensal a partir do primeiro ponto:
#   I_agg(m) = I_agg(m-1) × (1 + var_agg(m)/100)
#   I_agg(2000-01) = 100  (base rebased pra comparabilidade)
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

RECON_CSV   <- "data/cpi_cpius_recon.csv"
PESOS_CSV   <- "data/cpi_cpius_pesos.csv"
RECIPE_CSV  <- "scripts/bls_maps/custom_aggregations.csv"
OUT_CSV     <- "data/cpi_cpius_custom.csv"

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
    vw <- var_wide[[sf]]
    iw <- idx_wide[[sf]]

    var_series <- rep(NA_real_, length(datas))
    for (k in seq_along(datas)) {
      dk <- format(datas[k])
      if (!(dk %in% rownames(vw))) next
      if (!(dk %in% rownames(w_peso))) next
      vrow <- vw[dk, ]
      wrow <- w_peso[dk, ]
      if (method == "exclude") {
        if (is.na(base_cat) || !(base_cat %in% names(vrow))) next
        v_base <- as.numeric(vrow[[base_cat]])
        w_base <- as.numeric(wrow[[base_cat]])
        num <- v_base * w_base
        den <- w_base
        ok <- is.finite(v_base) && is.finite(w_base)
        for (e in excl) {
          if (!(e %in% names(vrow))) { ok <- FALSE; break }
          ve <- as.numeric(vrow[[e]])
          we <- as.numeric(wrow[[e]])
          if (!is.finite(ve) || !is.finite(we)) { ok <- FALSE; break }
          num <- num - ve * we
          den <- den - we
        }
        if (ok && is.finite(den) && den > 0) {
          var_series[k] <- num / den
        }
      } else if (method == "sum") {
        num <- 0; den <- 0; ok <- length(incl) > 0
        for (i in incl) {
          if (!(i %in% names(vrow))) { ok <- FALSE; break }
          vi <- as.numeric(vrow[[i]])
          wi <- as.numeric(wrow[[i]])
          if (!is.finite(vi) || !is.finite(wi)) { ok <- FALSE; break }
          num <- num + vi * wi
          den <- den + wi
        }
        if (ok && den > 0) var_series[k] <- num / den
      } else {
        stop(sprintf("method desconhecido: %s", method))
      }
    }

    # Reconstroi indice: base jan/2000 = 100. Primeiro var eh NA (jan/2000).
    idx_series <- rep(NA_real_, length(datas))
    idx_series[1] <- 100
    for (k in 2:length(datas)) {
      if (is.finite(var_series[k]) && is.finite(idx_series[k-1])) {
        idx_series[k] <- idx_series[k-1] * (1 + var_series[k] / 100)
      } else {
        # gap: carry forward
        idx_series[k] <- idx_series[k-1]
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
  }
}

out <- do.call(rbind, out_rows)
out <- out[order(out$date, out$category_code, out$sa_flag), ]

dir.create("data", showWarnings = FALSE, recursive = TRUE)
write.csv(out, OUT_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("\n[3] %d linhas -> %s\n", nrow(out), OUT_CSV))

# Sanity: ultimo ponto NSA por recipe
cat("\n[Sanity] Ultimo ponto (NSA) por agregado:\n")
last_d <- max(out$date)
last <- out[out$date == last_d & out$sa_flag == "NSA", ]
last <- last[order(-abs(last$value_var_yoy)), ]
print(last[, c("category_code","date","value_index","value_var_mm","value_var_yoy")],
      row.names = FALSE, right = FALSE)
cat("\nOK.\n")
