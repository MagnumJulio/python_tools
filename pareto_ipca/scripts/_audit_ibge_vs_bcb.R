#!/usr/bin/env Rscript
# _audit_ibge_vs_bcb.R — valida a recon IBGE-only (data/ipca_pareto_recon.csv)
# contra BCB SGS para as séries com SGS publicado, ao longo dos ~20 anos.
#
# Esperado: os 14 controles (admin/livres/industr/serv/alim_dom + núcleos +
# duráveis/semi-duráveis + comerc/ncomerc) devem bater com erro <0.01 pp em
# média na maioria, e <0.3 pp nos secundários. Diferenças marginais decorrem
# de suavização interna do BCB.
#
# alim_in_natura / alim_semi_elab / alim_industr NÃO entram nesse audit: o
# BCB não publica essas decomposições como SGS. SGS 1635/1636/1637 que já
# tentamos no passado são, na verdade, os GRUPOS 1/2/3 top-level do IPCA
# ("Alimentação e bebidas", "Habitação", "Artigos de residência") —
# provado por diff=0, corr=1 contra IBGE T7060 categorias 7170/7445/...
# Varredura de 190 códigos SGS em ranges plausíveis (27800-27900, 11400-11440,
# 4440-4480, 1700-1800, 16100-16140, 28000-28050) deu 0 hits com corr > 0.85
# contra alim_in/se/ind. Catálogo dadosabertos BCB também não tem essas séries.
# Conclusão: comparação direta impossível; nossa recon segue Tab.5 RI Dez/2019.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

PARETO_CSV <- "data/ipca_pareto_recon.csv"
if (!file.exists(PARETO_CSV)) stop("rode seed_ibge_history.R primeiro")
df <- read.csv(PARETO_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
df$date <- as.Date(df$date)

SGS_MAP <- list(
  administrados   = 4449L,  livres        = 11428L,
  industriais     = 27863L, servicos      = 10844L,
  alim_domicilio  = 27864L, nucleo_ex0    = 11427L,
  nucleo_ex3      = 27839L, duraveis      = 10843L,
  semiduraveis    = 10842L, nucleo_ma     = 11426L,
  nucleo_ms       = 4466L,  nucleo_dp     = 16122L,
  comerc          = 4447L,  ncomerc       = 4448L,
  # Onda 5 — núcleos NT_57/Dez-2025
  nucleo_exfe     = 28751L, nucleo_ex1    = 16121L,
  ex3_serv        = 29683L, ex3_ind       = 29684L,
  difusao         = 21379L
  # Sem SGS público: alim_in_natura / alim_semi_elab / alim_industr,
  # ndur_industr, servicos_subj, servicos_exsubj.
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

cat("Categoria          n     mean|d|    bias    RMSE   max|d|   janela\n")
cat("-----------------  ---  ---------  -------  -----  -------  -----------------\n")
for (cat_code in names(SGS_MAP)) {
  sgs <- SGS_MAP[[cat_code]]
  ibge <- df[df$category_code == cat_code, c("date","value")]
  if (nrow(ibge) == 0) next
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
cat("\nLeitura:\n")
cat("  mean|d| < 0.01pp = recon bate BCB perfeitamente (sanity ok)\n")
cat("  mean|d| > 0.10pp = divergência metodológica (esperada nas alim_in/se/ind)\n")
