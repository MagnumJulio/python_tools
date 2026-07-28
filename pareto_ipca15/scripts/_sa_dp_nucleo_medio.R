#!/usr/bin/env Rscript
# Dessazonaliza nucleo_dp e nucleo_medio via pacote `seasonal` (X-13ARIMA-SEATS
# nativo do R). Path alternativo ao wrapper corp x13_custom que esta bugado
# pra essas 2 series ('NoneType' object has no attribute 'startswith').
#
# Estrategia: dessazonalizar o INDICE (sempre positivo, log funciona), depois
# derivar var_sa via var[t] = (idx_sa[t]/idx_sa[t-1] - 1) * 100.
#
# Saida: data/ipca_pareto_sa_dp_medio.csv (long: date, category_code, var_sa, idx_sa)
# Uso: Rscript scripts/_sa_dp_nucleo_medio.R

suppressPackageStartupMessages(library(seasonal))

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
  cat(sprintf("[CWD] %s\n", getwd()))
}

IDX_CSV <- "data/ipca15_pareto_indice.csv"
OUT_CSV <- "data/ipca_pareto_sa_dp_medio.csv"

if (!file.exists(IDX_CSV)) {
  stop(sprintf("CSV de indice nao existe: %s — rode build_pareto_indice.R antes",
               IDX_CSV))
}

df <- read.csv(IDX_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
df$date <- as.Date(df$date)

cats <- c("nucleo_dp", "nucleo_medio")
out_list <- list()

for (cat in cats) {
  sub <- df[df$category_code == cat, c("date", "index")]
  sub <- sub[order(sub$date), ]
  if (nrow(sub) == 0) {
    cat(sprintf("[SKIP] %s nao encontrada no CSV\n", cat))
    next
  }
  start_y <- as.integer(format(min(sub$date), "%Y"))
  start_m <- as.integer(format(min(sub$date), "%m"))
  ts_idx  <- ts(sub$index, start = c(start_y, start_m), frequency = 12)

  cat(sprintf("\n[%s] %d obs (%s -> %s); tentando seas(log)...\n",
              cat, nrow(sub), format(min(sub$date), "%Y-%m"),
              format(max(sub$date), "%Y-%m")))

  res <- tryCatch(
    seas(ts_idx, transform.function = "log"),
    error = function(e) {
      cat(sprintf("  [WARN] log falhou: %s\n  fallback aditivo...\n",
                  conditionMessage(e)))
      tryCatch(
        seas(ts_idx, transform.function = "none"),
        error = function(e2) {
          cat(sprintf("  [FAIL] aditivo tambem falhou: %s\n",
                      conditionMessage(e2)))
          NULL
        }
      )
    }
  )
  if (is.null(res)) next

  sa_idx <- as.numeric(final(res))
  # var_sa derivado: pct change m/m do indice SA. 1o mes fica NA.
  var_sa <- c(NA_real_, (sa_idx[-1] / sa_idx[-length(sa_idx)] - 1) * 100)

  out_list[[cat]] <- data.frame(
    date = sub$date,
    category_code = cat,
    var_sa = round(var_sa, 6),
    idx_sa = round(sa_idx, 6),
    stringsAsFactors = FALSE
  )
  cat(sprintf("  [OK] %s SA: %d obs (incluindo NA inicial em var_sa)\n",
              cat, nrow(out_list[[cat]])))
  cat(sprintf("       idx_sa: ini=%.4f, fim=%.4f\n",
              sa_idx[1], sa_idx[length(sa_idx)]))
  cat(sprintf("       var_sa (ultimos 6m): %s\n",
              paste(round(tail(var_sa, 6), 3), collapse = ", ")))
}

if (length(out_list) == 0) {
  stop("Nenhuma categoria foi dessazonalizada com sucesso.")
}

out <- do.call(rbind, out_list)
out <- out[order(out$date, out$category_code), ]
write.csv(out, OUT_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("\n[OK] Saida: %s (%d linhas, %d categorias)\n",
            OUT_CSV, nrow(out), length(out_list)))
