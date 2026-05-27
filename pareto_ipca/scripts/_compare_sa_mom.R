#!/usr/bin/env Rscript
# Compara mom SA das 4 séries (admin, alim_dom, livres, serv) últimos 12m.
# Mimetiza o _try_sa() do load_pareto_to_sql.py:
#   1ª tentativa: transform.function="log"  (≡ Haver_Spec.spc, multiplicative)
#   fallback:     transform.function="none" (≡ Haver_Spec_Additive.spc)
# X-13ARIMA-SEATS via pacote `seasonal` (mesmo algoritmo do binário corp,
# defaults R em vez dos specs Haver — diferenças pequenas, mas existem).

suppressPackageStartupMessages(library(seasonal))

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
}

CSV <- "data/ipca_pareto_indice.csv"
df <- read.csv(CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
df$date <- as.Date(df$date)

cats <- c(admin   = "administrados",
          alim    = "alim_domicilio",
          livres  = "livres",
          serv    = "servicos")

sa_mom <- list()
for (nm in names(cats)) {
  c <- cats[[nm]]
  sub <- df[df$category_code == c, c("date", "index")]
  sub <- sub[order(sub$date), ]
  start_y <- as.integer(format(min(sub$date), "%Y"))
  start_m <- as.integer(format(min(sub$date), "%m"))
  ts_idx  <- ts(sub$index, start = c(start_y, start_m), frequency = 12)

  res <- tryCatch(
    seas(ts_idx, transform.function = "log"),
    error = function(e) {
      cat(sprintf("[WARN] %s falhou em log; fallback aditivo...\n", c))
      seas(ts_idx, transform.function = "none")
    }
  )
  sa_idx <- final(res)
  mom    <- (sa_idx / stats::lag(sa_idx, -1) - 1) * 100
  # mom é ts; pega últimos 12m
  yr  <- time(mom) %/% 1
  mo  <- round((time(mom) %% 1) * 12) + 1
  out <- data.frame(
    date = as.Date(sprintf("%d-%02d-01", yr, mo)),
    val  = as.numeric(mom),
    stringsAsFactors = FALSE
  )
  sa_mom[[nm]] <- out
}

mrg <- Reduce(function(a, b) merge(a, b, by = "date", all = TRUE),
              lapply(names(sa_mom), function(nm) {
                d <- sa_mom[[nm]]
                names(d)[2] <- nm
                d
              }))
mrg <- mrg[order(mrg$date), ]
mrg <- tail(mrg, 12)

cat("\nMoM SA (%) — X-13 defaults — últimos 12 meses\n\n")
mrg_out <- mrg
mrg_out[, c("admin", "alim", "livres", "serv")] <-
  round(mrg_out[, c("admin", "alim", "livres", "serv")], 3)
mrg_out$date <- format(mrg_out$date, "%Y-%m")
print(mrg_out, row.names = FALSE)
