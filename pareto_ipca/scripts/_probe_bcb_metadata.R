#!/usr/bin/env Rscript
# _probe_bcb_metadata.R — descobre o que SGS 1635/1636/1637/27864 realmente são.
# Hipóteses: (a) variação mensal, (b) variação 12m, (c) dessazonalizada, (d) outra.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

fetch <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  for (try in 1:3) {
    r <- tryCatch(GET(url, timeout(60)), error = function(e) NULL)
    if (!is.null(r) && status_code(r) == 200) {
      txt <- content(r, "text", encoding = "UTF-8")
      if (substr(txt, 1, 1) != "<") {
        raw <- fromJSON(txt)
        return(data.frame(date = as.Date(raw$data, format = "%d/%m/%Y"),
                          value = as.numeric(raw$valor)))
      }
    }; Sys.sleep(2 * try)
  }; stop("BCB falhou")
}

# IPCA mensal oficial (variação a/m): SGS 433. Pra comparar magnitudes.
SERIES <- list(
  list(c = 433L,   nm = "IPCA - var. mensal (oficial)"),
  list(c = 4449L,  nm = "Administrados - var. mensal"),
  list(c = 27864L, nm = "Alim. domicílio - var. mensal"),
  list(c = 1635L,  nm = "ALIM IN-NATURA (?)"),
  list(c = 1636L,  nm = "ALIM SEMI-ELAB (?)"),
  list(c = 1637L,  nm = "ALIM INDUSTR (?)")
)

cat("Série            n        início      fim        média    desvio    min       max       %abs<0.5  %abs>3\n")
cat("---------------- ----  ----------  ----------  -------  -------  -------  -------  --------  ------\n")
for (s in SERIES) {
  d <- fetch(s$c)
  v <- d$value[!is.na(d$value)]
  cat(sprintf("SGS %-5d %-4s  %4d  %s  %s  %+7.3f  %7.3f  %+7.2f  %+7.2f  %4.0f%%      %4.0f%%\n",
              s$c, "", length(v),
              format(min(d$date)), format(max(d$date)),
              mean(v), sd(v), min(v), max(v),
              100*mean(abs(v) < 0.5), 100*mean(abs(v) > 3)))
  cat(sprintf("  %s\n", s$nm))
}

cat("\n--- Conferência: SGS 1635 ano completo 2018 (mês a mês) ---\n")
d <- fetch(1635L)
d2018 <- d[format(d$date, "%Y") == "2018", ]
print(d2018, row.names = FALSE)
cat(sprintf("  Soma 2018: %+.3f%%\n", sum(d2018$value)))
cat(sprintf("  Var. acum. composta 2018: %+.3f%%\n",
            (prod(1 + d2018$value/100) - 1) * 100))

cat("\n--- Conferência: SGS 1635 ano completo 2022 ---\n")
d2022 <- d[format(d$date, "%Y") == "2022", ]
print(d2022, row.names = FALSE)
cat(sprintf("  Soma 2022: %+.3f%%\n", sum(d2022$value)))
cat(sprintf("  Var. acum. composta 2022: %+.3f%%\n",
            (prod(1 + d2022$value/100) - 1) * 100))

cat("\n--- IBGE alim_in_natura 2018 (nossa recon) ---\n")
df <- read.csv("data/ipca_pareto_recon.csv", stringsAsFactors = FALSE)
df$date <- as.Date(df$date)
ibge2018 <- df[df$category_code == "alim_in_natura" & format(df$date, "%Y") == "2018", c("date","value")]
print(ibge2018, row.names = FALSE)
cat(sprintf("  Var. acum. composta 2018 (nossa): %+.3f%%\n",
            (prod(1 + ibge2018$value/100) - 1) * 100))
