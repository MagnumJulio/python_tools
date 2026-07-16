#!/usr/bin/env Rscript
# fetch_bls_cpiu.R
#
# Fetcha índice CPI-U (Table 1 do release mensal do BLS) das 36 agregações
# hierárquicas mapeadas em scripts/bls_maps/cpiu_table_1.csv (headline → filhos
# até 4 níveis de profundidade: food/energy/core > subgrupos > itens folha).
# Para cada item, baixa SA (CUSR0000<item>) + NSA (CUUR0000<item>) via
# BLS Public Data API v2 (payload JSON POST, batches de até 50 séries).
#
# Chave da API (opcional): env var BLS_API_KEY. Sem chave, a API v2 permite
# 25 séries por request e 25 requests/dia. Com chave (gratuita em
# https://data.bls.gov/registrationEngine/): 50 séries por request e 500
# requests/dia — obrigatório se rodar diariamente com histórico grande.
#
# Saídas:
#   data/cpi_cpius_recon.csv   — long (date, category_code, sa_flag, series_id,
#                                 value_index, value_var_mm, value_var_yoy)
#   data/cpi_cpius_indice.csv  — long (date, category_code, sa_flag, index)
#                                 rebased em jan/2000=100 pra comparabilidade
#
# Uso:
#   cd pareto_cpius
#   Rscript scripts/fetch_bls_cpiu.R                 # 2000 → atual
#   START_YEAR=1990 Rscript scripts/fetch_bls_cpiu.R # janela custom
#
# Referências:
#   BLS API v2 docs: https://www.bls.gov/developers/api_signature_v2.htm
#   Item codes (CPI-U): https://download.bls.gov/pub/time.series/cu/cu.item

# Auto-cwd: descobre raiz do projeto via --file= e seta como cwd.
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

suppressPackageStartupMessages({
  library(httr)
  library(jsonlite)
})

# Proxy opcional (empresa) — no-op em casa.
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

BLS_URL      <- "https://api.bls.gov/publicAPI/v2/timeseries/data/"
MAP_CSV      <- "scripts/bls_maps/cpiu_table_1.csv"
OUT_RECON    <- "data/cpi_cpius_recon.csv"
OUT_INDICE   <- "data/cpi_cpius_indice.csv"
API_KEY      <- Sys.getenv("BLS_API_KEY", unset = "")
BATCH_SIZE   <- if (nzchar(API_KEY)) 50L else 25L
YEAR_STRIDE  <- 20L   # BLS v2 aceita até 20 anos por request.
START_YEAR   <- as.integer(Sys.getenv("START_YEAR", unset = "2000"))
END_YEAR     <- as.integer(format(Sys.Date(), "%Y"))

dir.create("data", showWarnings = FALSE, recursive = TRUE)

if (!file.exists(MAP_CSV)) stop(sprintf("Mapa nao encontrado: %s", MAP_CSV))
smap <- read.csv(MAP_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")

# ---------------------------------------------------------------------------
# 1. Constrói lista de series_id (SA + NSA por item).

build_series_ids <- function(smap) {
  # BLS series ID (CPI-U): CU + [U|S] + R + 0000 + <item_code>
  ur <- data.frame(category_code = smap$category_code,
                   sa_flag       = "NSA",
                   series_id     = paste0("CUUR0000", smap$item_code),
                   item_code     = smap$item_code,
                   label         = smap$label,
                   stringsAsFactors = FALSE)
  sr <- data.frame(category_code = smap$category_code,
                   sa_flag       = "SA",
                   series_id     = paste0("CUSR0000", smap$item_code),
                   item_code     = smap$item_code,
                   label         = smap$label,
                   stringsAsFactors = FALSE)
  rbind(ur, sr)
}

series_df <- build_series_ids(smap)
cat(sprintf("[1] Mapeadas %d series (%d categorias x SA+NSA)\n",
            nrow(series_df), nrow(smap)))
cat(sprintf("    Batch size: %d (%s BLS_API_KEY)\n",
            BATCH_SIZE, if (nzchar(API_KEY)) "com" else "SEM"))

# ---------------------------------------------------------------------------
# 2. Fetcher: POSTa batch pra BLS API v2, respeitando limite de 20 anos.

post_bls_batch <- function(sids, y_start, y_end) {
  body <- list(
    seriesid        = as.list(sids),
    startyear       = as.character(y_start),
    endyear         = as.character(y_end),
    catalog         = FALSE,
    calculations    = FALSE,
    annualaverage   = FALSE
  )
  if (nzchar(API_KEY)) body$registrationkey <- API_KEY
  r <- POST(BLS_URL,
            body = toJSON(body, auto_unbox = TRUE),
            content_type_json(),
            accept_json(),
            timeout(90))
  stop_for_status(r)
  parsed <- content(r, as = "parsed", simplifyVector = FALSE)
  if (!identical(parsed$status, "REQUEST_SUCCEEDED")) {
    stop(sprintf("BLS API status=%s messages=%s",
                 parsed$status,
                 paste(unlist(parsed$message), collapse = "; ")))
  }
  parsed$Results$series
}

parse_series_json <- function(sblock) {
  # sblock = { seriesID: "...", data: [ {year, period, periodName, value, ...}, ... ] }
  sid <- sblock$seriesID
  d   <- sblock$data
  if (!length(d)) return(NULL)
  # period vem como M01..M12; M13 = annual average (ignoramos).
  keep <- vapply(d, function(x) grepl("^M(0[1-9]|1[0-2])$", x$period), logical(1))
  d <- d[keep]
  if (!length(d)) return(NULL)
  yr  <- vapply(d, function(x) as.integer(x$year), integer(1))
  mo  <- vapply(d, function(x) as.integer(sub("^M", "", x$period)), integer(1))
  val <- vapply(d, function(x) suppressWarnings(as.numeric(x$value)), numeric(1))
  data.frame(
    series_id = sid,
    date      = as.Date(sprintf("%04d-%02d-01", yr, mo)),
    value     = val,
    stringsAsFactors = FALSE
  )
}

# BLS v2 exige janela <= 20 anos por request. Se START_YEAR..END_YEAR > 20,
# quebra em sub-janelas e concatena.
year_windows <- function(y0, y1, stride) {
  out <- list(); k <- y0
  while (k <= y1) {
    j <- min(y1, k + stride - 1L)
    out[[length(out) + 1]] <- c(k, j)
    k <- j + 1L
  }
  out
}

wins <- year_windows(START_YEAR, END_YEAR, YEAR_STRIDE)
sid_all <- series_df$series_id
n_batches <- ceiling(length(sid_all) / BATCH_SIZE)

all_rows <- vector("list", 0)
cat(sprintf("[2] Baixando %d series em %d batch(es) x %d janela(s) de anos...\n",
            length(sid_all), n_batches, length(wins)))

for (bi in seq_len(n_batches)) {
  i0 <- (bi - 1L) * BATCH_SIZE + 1L
  i1 <- min(bi * BATCH_SIZE, length(sid_all))
  sids <- sid_all[i0:i1]
  for (w in wins) {
    cat(sprintf("    batch %d/%d, anos %d-%d (%d series)...\n",
                bi, n_batches, w[1], w[2], length(sids)))
    blocks <- post_bls_batch(sids, w[1], w[2])
    for (b in blocks) {
      pr <- parse_series_json(b)
      if (!is.null(pr) && nrow(pr)) all_rows[[length(all_rows) + 1]] <- pr
    }
    # Cortesia com a API — pausa curta entre requests.
    Sys.sleep(0.3)
  }
}

raw <- do.call(rbind, all_rows)
raw <- raw[!is.na(raw$value), ]
raw <- unique(raw)
cat(sprintf("    %d linhas raw baixadas\n", nrow(raw)))

# ---------------------------------------------------------------------------
# 3. Merge com metadata (category_code, sa_flag, label).

joined <- merge(raw, series_df[, c("series_id", "category_code", "sa_flag", "label")],
                by = "series_id", all.x = TRUE)
joined <- joined[order(joined$category_code, joined$sa_flag, joined$date), ]

# ---------------------------------------------------------------------------
# 4. Var mensal e var 12m (yoy).

compute_vars <- function(df) {
  df <- df[order(df$date), ]
  df$value_var_mm  <- c(NA_real_, diff(df$value) / head(df$value, -1) * 100)
  # yoy: exige 12 meses de defasagem exata.
  n <- nrow(df)
  df$value_var_yoy <- NA_real_
  if (n > 12) {
    lag12 <- df$value[1:(n - 12)]
    cur   <- df$value[13:n]
    df$value_var_yoy[13:n] <- (cur / lag12 - 1) * 100
  }
  df
}

by_key <- split(joined, list(joined$category_code, joined$sa_flag), drop = TRUE)
by_key <- lapply(by_key, compute_vars)
recon <- do.call(rbind, by_key)
recon <- recon[order(recon$date, recon$category_code, recon$sa_flag), ]

recon_out <- data.frame(
  date          = recon$date,
  category_code = recon$category_code,
  sa_flag       = recon$sa_flag,
  series_id     = recon$series_id,
  value_index   = round(recon$value, 6),
  value_var_mm  = round(recon$value_var_mm, 6),
  value_var_yoy = round(recon$value_var_yoy, 6),
  stringsAsFactors = FALSE
)

write.csv(recon_out, OUT_RECON, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("[3] %d linhas -> %s\n", nrow(recon_out), OUT_RECON))

# ---------------------------------------------------------------------------
# 5. Índice rebased jan/2000=100 (base comum comparável).

BASE_DATE <- as.Date("2000-01-01")

rebased <- do.call(rbind, lapply(by_key, function(df) {
  df <- df[order(df$date), ]
  ref <- df$value[df$date == BASE_DATE]
  if (!length(ref) || is.na(ref) || ref <= 0) {
    ref <- df$value[which(!is.na(df$value))[1]]  # fallback: 1º valor
  }
  df$index <- df$value / ref * 100
  df[, c("date", "category_code", "sa_flag", "index")]
}))
rebased <- rebased[order(rebased$date, rebased$category_code, rebased$sa_flag), ]
rebased$index <- round(rebased$index, 6)
write.csv(rebased, OUT_INDICE, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("[4] %d linhas -> %s (base %s = 100)\n",
            nrow(rebased), OUT_INDICE, format(BASE_DATE)))

# ---------------------------------------------------------------------------
# 6. Resumo por categoria (audit rápido).

cat("\n[5] Resumo (último ponto NSA por categoria, ordenado por yoy):\n")
last_by_key <- do.call(rbind, lapply(
  split(recon, list(recon$category_code, recon$sa_flag), drop = TRUE),
  function(df) df[which.max(df$date), ]
))
last_nsa <- last_by_key[last_by_key$sa_flag == "NSA", ]
last_nsa$value_index <- last_nsa$value
last_nsa <- last_nsa[order(-abs(last_nsa$value_var_yoy)), ]
print(last_nsa[, c("category_code", "date", "value_index", "value_var_mm", "value_var_yoy")],
      row.names = FALSE, right = FALSE)

cat("\nOK. Rode `Rscript scripts/build_cpi_indice.R` se quiser rebases customizados.\n")
