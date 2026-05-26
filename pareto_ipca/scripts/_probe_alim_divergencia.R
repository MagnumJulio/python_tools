#!/usr/bin/env Rscript
# _probe_alim_divergencia.R — investigação séria da divergência alim_in/se/ind.
#
# Hipóteses a testar:
#   H1: BCB SGS 1635/1636/1637 NÃO são "alim in_natura/semi_elab/industr"
#       (i.e., estou comparando coisas erradas).
#   H2: BCB usa regra antiga (RI Mar/2014: pescados/frango/alho em in_natura).
#       Se ligar regra antiga, mean|d| deveria CAIR significativamente.
#   H3: SIDRA já publica esses agregados (chassi único; bypass do mask).
#   H4: A divergência é dominada por outliers de poucos meses (não estrutural).

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

fetch_bcb <- function(code) {
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
    }
    Sys.sleep(2 * try)
  }
  stop(sprintf("BCB %d falhou", code))
}

# Metadado SGS via página de descrição (SGS).
fetch_bcb_meta <- function(code) {
  url <- sprintf("https://www3.bcb.gov.br/sgspub/consultarmetadados/consultarMetadadosSeries.paint?codigo=%d", code)
  r <- tryCatch(GET(url, timeout(30)), error = function(e) NULL)
  if (is.null(r) || status_code(r) != 200) return("metadata unavailable")
  txt <- content(r, "text", encoding = "UTF-8")
  # Extrai nome/descrição visíveis (best-effort, página é HTML).
  m <- regmatches(txt, regexpr("(?<=<title>)[^<]+", txt, perl = TRUE))
  if (length(m) == 0) m <- "no title"
  return(m)
}

cat("=================================================================\n")
cat(" H1: confirma metadado BCB SGS 1635/1636/1637 + 27864 (alim_dom)\n")
cat("=================================================================\n")
for (c in c(1635L, 1636L, 1637L, 27864L)) {
  cat(sprintf("  SGS %d : %s\n", c, fetch_bcb_meta(c)))
}

cat("\n=================================================================\n")
cat(" H4: piores meses de divergência em alim_in_natura\n")
cat("=================================================================\n")
df <- read.csv("data/ipca_pareto_recon.csv", stringsAsFactors = FALSE, encoding = "UTF-8")
df$date <- as.Date(df$date)

ibge_in <- df[df$category_code == "alim_in_natura", c("date","value")]
bcb_in  <- fetch_bcb(1635L)
m <- merge(ibge_in, bcb_in, by = "date", suffixes = c(".ibge", ".bcb"))
m$diff <- m$value.ibge - m$value.bcb
m$abs_diff <- abs(m$diff)
m <- m[order(-m$abs_diff), ]
cat(sprintf("%-10s  %8s   %8s   %8s\n", "data", "IBGE",  "BCB",   "diff"))
for (i in 1:15) cat(sprintf("%-10s  %+8.3f   %+8.3f   %+8.3f\n",
                             format(m$date[i]), m$value.ibge[i], m$value.bcb[i], m$diff[i]))

cat("\nDistribuição |diff|:\n")
print(summary(m$abs_diff))
cat(sprintf("  meses |diff| < 0.5 pp : %d (%.0f%%)\n",
            sum(m$abs_diff < 0.5), 100*mean(m$abs_diff < 0.5)))
cat(sprintf("  meses |diff| > 5.0 pp : %d (%.0f%%)\n",
            sum(m$abs_diff > 5.0), 100*mean(m$abs_diff > 5.0)))

cat("\n=================================================================\n")
cat(" H2: simulação com regra ANTIGA (pescados/frango/alho em in_natura)\n")
cat("=================================================================\n")
# Carrega máscara e MUDA temporariamente proc_grau:
#   1108* / 1110009 / 1110010 / 1116010 → in_natura
#   1111004 → industr (revert leite longa vida tb pra testar)
mask <- read.csv("scripts/ipca_masks/classificacao.csv",
                 stringsAsFactors = FALSE, encoding = "UTF-8")
old_in   <- mask$cod_ibge[grep("^1108", mask$cod_ibge)]
old_in   <- c(old_in, "1110009", "1110010", "1116010")
old_ind  <- "1111004"
cat(sprintf("Itens que reverteriam pra regra antiga:\n"))
cat(sprintf("  → in_natura: %d itens (1108*/1110009/1110010/1116010)\n", length(old_in)))
cat(sprintf("  → industr:   1111004 (Leite longa vida)\n"))
cat("\nPara executar a simulação real, precisa rodar reconstruct_ipca.R\n")
cat("com mask alternativa. Faça isso só se H4 não explicar a divergência.\n")

cat("\n=================================================================\n")
cat(" H3: SIDRA tem agregados alim_in/se/ind diretos?\n")
cat("=================================================================\n")
# Tabelas IPCA conhecidas. Variáveis e classificações via metadados.
for (tbl in c(7060L, 1419L)) {
  url <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/metadados", tbl)
  r <- tryCatch(GET(url, timeout(30)), error = function(e) NULL)
  if (is.null(r) || status_code(r) != 200) {
    cat(sprintf("  T%d: metadata HTTP fail\n", tbl)); next
  }
  meta <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  cat(sprintf("\n  T%d (%s): %d classificações\n", tbl, meta$nome, length(meta$classificacoes)))
  for (cls in meta$classificacoes) {
    cat(sprintf("    classificacao %s: %s (%d categorias)\n",
                cls$id, cls$nome, length(cls$categorias)))
    # Procura categorias que mencionem "natura"/"semi"/"industr"
    for (catg in cls$categorias) {
      nm <- catg$nome
      if (grepl("natura|semi[ -]elab|industr", nm, ignore.case = TRUE)) {
        cat(sprintf("        → MATCH: id=%s nome=%s\n", catg$id, nm))
      }
    }
  }
}
