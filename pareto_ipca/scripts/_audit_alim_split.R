#!/usr/bin/env Rscript
# _audit_alim_split.R — audita alim_in/se/ind contra BCB SGS 1635/1636/1637
# separando pré-2020 (estrutura "atual" RI 2019 Tab.4) vs pós-2020 (Tab.5 nova).
#
# Hipótese: nossa recon usa Tab.5 (regra atual) em toda janela; BCB usa Tab.4
# pré-2020 e Tab.5 pós-2020. Divergência pré-2020 deve ser maior.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

df <- read.csv("data/ipca_pareto_recon.csv", stringsAsFactors = FALSE, encoding = "UTF-8")
df$date <- as.Date(df$date)

fetch_bcb <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  for (try in 1:3) {
    r <- tryCatch(GET(url, timeout(120)), error = function(e) NULL)
    if (!is.null(r) && status_code(r) == 200) {
      txt <- content(r, "text", encoding = "UTF-8")
      if (substr(txt, 1, 1) == "<") { Sys.sleep(2 * try); next }
      raw <- fromJSON(txt)
      return(data.frame(date  = as.Date(raw$data, format = "%d/%m/%Y"),
                        value = as.numeric(raw$valor)))
    }
    Sys.sleep(2 * try)
  }
  stop(sprintf("BCB %d falhou", code))
}

MAP <- list(alim_in_natura = 1635L, alim_semi_elab = 1636L, alim_industr = 1637L)
CUTOFF <- as.Date("2020-01-01")

cat("\nCategoria         Janela      n    mean|d|   bias    RMSE   max|d|\n")
cat("---------------  ---------  ---  --------  -------  -----  ------\n")
for (cat_code in names(MAP)) {
  sgs <- MAP[[cat_code]]
  ibge <- df[df$category_code == cat_code, c("date","value")]
  bcb <- fetch_bcb(sgs)
  m <- merge(ibge, bcb, by = "date", suffixes = c(".ibge", ".bcb"))
  for (period in list(list(lab = "pré-2020", sel = m$date <  CUTOFF),
                      list(lab = "pós-2020", sel = m$date >= CUTOFF),
                      list(lab = "completo", sel = rep(TRUE, nrow(m))))) {
    s <- m[period$sel, ]
    d <- s$value.ibge - s$value.bcb
    d <- d[!is.na(d)]
    cat(sprintf("  %-15s %-9s  %3d  %.4f   %+.4f  %.3f  %.4f\n",
                cat_code, period$lab, length(d), mean(abs(d)), mean(d),
                sqrt(mean(d^2)), max(abs(d))))
  }
}
