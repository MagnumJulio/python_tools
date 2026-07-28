#!/usr/bin/env Rscript
# _audit_ibge_vs_bcb.R — auditoria IPCA-15 (data/ipca15_pareto_recon.csv)
# contra BCB SGS. Duas partes:
#
# [A] Validação REAL: `total` (nosso headline) vs SGS 7478 (IPCA-15 headline).
#     Esperado: mean|d| ~0.0000pp. Único SGS confirmado como IPCA-15 puro.
#
# [B] Diagnóstico do GAP IPCA-15 vs IPCA cheio: nossos breakdowns vs SGS
#     IPCA CHEIO correspondentes. Diferenças ~0.1-0.4pp com corr 0.75-0.96
#     são o gap metodológico esperado (janelas de coleta divergem em ~15d),
#     NÃO erro da nossa recon. Serve só como sanity qualitativo.
#
# Descoberta 2026-07-27 (probe `_probe_score.py` sobre ~230 SGS candidatos):
# o BCB SÓ publica IPCA-15 como SGS pro headline. Nenhum breakdown do IPCA-15
# (admin, livres, industr, serv, núcleos, ...) tem código SGS dedicado. Portanto
# comparar nosso breakdown IPCA-15 contra SGS 4449/11428/27863/... vira apenas
# medida do gap IPCA-15 vs IPCA cheio.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

PARETO_CSV <- "data/ipca15_pareto_recon.csv"
if (!file.exists(PARETO_CSV)) stop("rode seed_ibge_history.R primeiro")
df <- read.csv(PARETO_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
df$date <- as.Date(df$date)

# [A] Validação real — único SGS legítimo IPCA-15
SGS_IPCA15 <- list(total = 7478L)

# [B] SGS IPCA CHEIO — usados só como diagnóstico do gap IPCA-15 vs IPCA cheio.
# Mean|d| esperado 0.1-0.4pp (corr 0.75-0.96) — NÃO valida a recon IPCA-15.
SGS_IPCA_CHEIO <- list(
  administrados   = 4449L,  livres        = 11428L,
  industriais     = 27863L, servicos      = 10844L,
  alim_domicilio  = 27864L, nucleo_ex0    = 11427L,
  nucleo_ex3      = 27839L, duraveis      = 10843L,
  semiduraveis    = 10842L, nucleo_ma     = 11426L,
  nucleo_ms       = 4466L,  nucleo_dp     = 16122L,
  comerc          = 4447L,  ncomerc       = 4448L,
  nucleo_exfe     = 28751L, nucleo_ex1    = 16121L,
  ex3_serv        = 29683L, ex3_ind       = 29684L,
  difusao         = 21379L, nucleo_p55    = 28750L
)

fetch_bcb <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  for (try in 1:3) {
    r <- tryCatch(GET(url, timeout(120)), error = function(e) NULL)
    if (!is.null(r) && status_code(r) == 200) {
      raw <- fromJSON(content(r, "text", encoding = "UTF-8"))
      return(data.frame(date  = as.Date(raw$data, format = "%d/%m/%Y"),
                        value = as.numeric(raw$valor)))
    }
    Sys.sleep(2 * try)
  }
  stop(sprintf("BCB SGS %d falhou após 3 tentativas", code))
}

audit <- function(sgs_map, header) {
  cat(sprintf("\n%s\n", header))
  cat("Categoria          n     mean|d|    bias    RMSE   max|d|   janela\n")
  cat("-----------------  ---  ---------  -------  -----  -------  -----------------\n")
  for (cat_code in names(sgs_map)) {
    sgs <- sgs_map[[cat_code]]
    ibge <- df[df$category_code == cat_code, c("date","value")]
    if (nrow(ibge) == 0) { cat(sprintf("  %-17s sem recon\n", cat_code)); next }
    bcb <- tryCatch(fetch_bcb(sgs), error = function(e) NULL)
    if (is.null(bcb)) { cat(sprintf("  %-17s FAIL fetch\n", cat_code)); next }
    m <- merge(ibge, bcb, by = "date", suffixes = c(".ibge", ".bcb"))
    if (nrow(m) == 0) { cat(sprintf("  %-17s sem overlap\n", cat_code)); next }
    d <- m$value.ibge - m$value.bcb
    d <- d[!is.na(d)]
    cat(sprintf("  %-17s  %3d  %.4f   %+.4f  %.3f  %.4f   %s → %s\n",
                cat_code, length(d), mean(abs(d)), mean(d),
                sqrt(mean(d^2)), max(abs(d)),
                format(min(m$date), "%Y-%m"), format(max(m$date), "%Y-%m")))
  }
}

audit(SGS_IPCA15, "[A] VALIDAÇÃO — recon IPCA-15 vs SGS IPCA-15 (deve bater com mean|d| ~0.00pp)")
audit(SGS_IPCA_CHEIO, "[B] DIAGNÓSTICO — recon IPCA-15 vs SGS IPCA CHEIO (gap ~0.1-0.4pp esperado)")

cat("\nLeitura:\n")
cat("  [A] total vs SGS 7478: mean|d| ~0.00pp = recon IPCA-15 correta.\n")
cat("  [B] mean|d| 0.1-0.4pp: gap normal IPCA-15 vs IPCA cheio (não é erro).\n")
cat("      corr esperada 0.75-0.96 (medida no probe 2026-07-27).\n")
