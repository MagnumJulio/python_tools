#!/usr/bin/env Rscript
# build_cpi_indice.R
#
# Rebase customizavel do indice CPI-U a partir de data/cpi_cpius_recon.csv.
# Reescreve data/cpi_cpius_indice.csv com nova base.
#
# O fetch_bls_cpiu.R ja produz o indice em jan/2000=100 direto. Este script
# existe pra permitir rebases custom sem re-fetchar a API BLS.
#
# Bases suportadas:
#   BASE_DATE=2000-01-01 (default, alinhado com fetch_bls_cpiu.R)
#   BASE_DATE=1982-07-01 (base nativa BLS 1982-84=100)
#   BASE_DATE=2019-12-01 (pre-pandemia, util pra graficos)
#
# Uso:
#   Rscript scripts/build_cpi_indice.R
#   BASE_DATE=2019-12-01 Rscript scripts/build_cpi_indice.R

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

RECON_CSV <- "data/cpi_cpius_recon.csv"
IDX_CSV   <- "data/cpi_cpius_indice.csv"
BASE_DATE <- as.Date(Sys.getenv("BASE_DATE", unset = "2000-01-01"))

if (!file.exists(RECON_CSV)) {
  stop(sprintf("CSV recon nao existe: %s. Rode fetch_bls_cpiu.R primeiro.", RECON_CSV))
}

cat(sprintf("[1] Lendo %s...\n", RECON_CSV))
src <- read.csv(RECON_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
src$date <- as.Date(src$date)
cat(sprintf("    %d linhas, %d categorias x SA/NSA, %s -> %s\n",
            nrow(src), length(unique(src$category_code)),
            format(min(src$date)), format(max(src$date))))

# Rebase por (category_code, sa_flag). Se BASE_DATE nao existir pra alguma
# combinacao, cai em fallback (1o valor nao-NA).
cat(sprintf("\n[2] Rebasing em %s = 100...\n", format(BASE_DATE)))
by_key <- split(src, list(src$category_code, src$sa_flag), drop = TRUE)

rebased <- do.call(rbind, lapply(by_key, function(df) {
  df <- df[order(df$date), ]
  ref <- df$value_index[df$date == BASE_DATE]
  if (!length(ref) || is.na(ref) || ref <= 0) {
    ref <- df$value_index[which(!is.na(df$value_index))[1]]
    warning(sprintf("[%s/%s] %s nao encontrado; usando 1o valor",
                    df$category_code[1], df$sa_flag[1], format(BASE_DATE)))
  }
  data.frame(
    date          = df$date,
    category_code = df$category_code,
    sa_flag       = df$sa_flag,
    index         = round(df$value_index / ref * 100, 6),
    stringsAsFactors = FALSE
  )
}))
rebased <- rebased[order(rebased$date, rebased$category_code, rebased$sa_flag), ]

write.csv(rebased, IDX_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("[3] %d linhas -> %s (base %s = 100)\n",
            nrow(rebased), IDX_CSV, format(BASE_DATE)))
cat("    OK.\n")
