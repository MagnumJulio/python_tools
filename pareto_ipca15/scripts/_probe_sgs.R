#!/usr/bin/env Rscript
# _probe_sgs.R — sonda candidatos a SGS pra ndur_industr / serv_subj / serv_exsubj
# antes de decidir se dá pra estender o seed dessas séries.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

# Candidatos prováveis (catálogo SGS BCB):
#   10841 = Bens não-duráveis (composite = ndur_industr + alim_in + alim_se — sabemos)
#   25254/27838/etc = núcleos de serviços subjacentes (hipóteses)
#   Vou tentar uma faixa e ver o que existe + bate em algo razoável.
CANDIDATES <- c(
  # Não-duráveis (10841 já sabemos; testar variantes)
  10841,
  # Serviços subjacentes / ex-subjacentes — códigos conhecidos do BCB
  4399,    # Núcleo serv subj (hipótese antiga)
  27840,   # Serv subj
  27841,   # Serv exsubj
  4395, 4396,  # outras hipóteses
  # Núcleo serviços agregado (referência)
  10844
)

probe <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  r <- tryCatch(GET(url, timeout(60)), error = function(e) NULL)
  if (is.null(r)) return(list(code = code, ok = FALSE, msg = "timeout/conn"))
  if (status_code(r) != 200) return(list(code = code, ok = FALSE, msg = sprintf("HTTP %d", status_code(r))))
  raw <- tryCatch(fromJSON(content(r, "text", encoding = "UTF-8")), error = function(e) NULL)
  if (is.null(raw) || !is.data.frame(raw) || nrow(raw) == 0)
    return(list(code = code, ok = FALSE, msg = "empty/parse-fail"))
  d <- data.frame(date = as.Date(raw$data, format = "%d/%m/%Y"),
                  value = as.numeric(raw$valor))
  list(code = code, ok = TRUE, n = nrow(d),
       date_min = format(min(d$date), "%Y-%m"),
       date_max = format(max(d$date), "%Y-%m"),
       last = tail(d$value, 1),
       data = d)
}

cat("Sondando candidatos SGS:\n")
results <- list()
for (cd in CANDIDATES) {
  r <- probe(cd)
  if (r$ok) {
    cat(sprintf("  SGS %5d  OK  %4d obs  %s → %s  último=%.4f\n",
                r$code, r$n, r$date_min, r$date_max, r$last))
    results[[as.character(cd)]] <- r$data
  } else {
    cat(sprintf("  SGS %5d  FAIL  %s\n", r$code, r$msg))
  }
}

# Pros candidatos OK, comparar com nossa recon
if (file.exists("scripts/outputs/ipca_reconstruido.csv")) {
  recon <- read.csv("scripts/outputs/ipca_reconstruido.csv", stringsAsFactors = FALSE)
  recon$date <- as.Date(paste0(substr(recon$periodo,1,4),"-",
                                substr(recon$periodo,5,6),"-01"))
  cat("\nMatch vs nossa recon (24 obs):\n")
  targets <- list(ndur_industr   = "var_ndind",
                  servicos_subj  = "var_serv_subj",
                  servicos_exsubj= "var_serv_exsubj")
  for (cd_str in names(results)) {
    bcb <- results[[cd_str]]
    names(bcb)[2] <- "bcb"
    for (tg in names(targets)) {
      col <- targets[[tg]]
      m <- merge(recon[, c("date", col)], bcb, by = "date")
      if (nrow(m) == 0) next
      m$d <- m[[col]] - m$bcb
      cat(sprintf("  SGS %s vs %-17s  n=%2d  mean|d|=%.4f bias=%+.4f corr=%.4f\n",
                  cd_str, tg, nrow(m),
                  mean(abs(m$d), na.rm = TRUE),
                  mean(m$d, na.rm = TRUE),
                  if (sd(m$bcb) > 0) cor(m[[col]], m$bcb) else NA))
    }
  }
}
