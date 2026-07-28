#!/usr/bin/env Rscript
# Confirma o que é SGS 1635/1636/1637 comparando contra IBGE diretamente.
# Hipótese da WebSearch: 1635 = "Alimentação e bebidas" (grupo IPCA),
# não "alim_in_natura".

suppressPackageStartupMessages({ library(httr); library(jsonlite) })
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

fetch_bcb <- function(code, ini="01/01/2020", fim="31/12/2023") {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json&dataInicial=%s&dataFinal=%s",
                 code, ini, fim)
  r <- GET(url, timeout(60))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"))
  data.frame(date = as.Date(raw$data, format = "%d/%m/%Y"),
             value = as.numeric(raw$valor))
}

fetch_sidra <- function(tbl, per, var, cls315) {
  url <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=315[%s]",
                 tbl, per, var, cls315)
  r <- GET(url, timeout(60))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  out <- list()
  for (item in raw[[1]]$resultados) {
    for (s in item$series) {
      for (p in names(s$serie)) {
        out[[length(out)+1]] <- data.frame(
          periodo = p, valor = as.numeric(s$serie[[p]]),
          cls = item$classificacoes[[1]]$categoria[[1]], stringsAsFactors = FALSE)
      }
    }
  }
  do.call(rbind, out)
}

# SIDRA T7060 classificacao 315: categoria 7170 = "1.Alimentação e bebidas" (grupo 1)
# categoria 7445 = "11.Alimentação no domicílio" (subgrupo 11)
# categoria 7170 deve bater com SGS 1635 SE 1635 = grupo 1
cat("=== SGS 1635 vs IBGE T7060 cls315 cat=7170 (grupo 1 'Alimentação e bebidas') ===\n")
cat("Janela: 2020-01 a 2023-12 (T7060 cobre só 2020+)\n\n")

bcb_1635 <- fetch_bcb(1635L)
cat(sprintf("SGS 1635 obtido: %d obs\n", nrow(bcb_1635)))

# IBGE: grupo 1 'Alimentação e bebidas' via T7060
# Vamos achar o id correto da categoria.
meta <- fromJSON(content(GET("https://servicodados.ibge.gov.br/api/v3/agregados/7060/metadados", timeout(60)),
                          "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
cats <- meta$classificacoes[[1]]$categorias
g1_id <- NULL; sg11_id <- NULL
for (c in cats) {
  if (grepl("^1\\.Alimenta", c$nome))   g1_id  <- c$id
  if (grepl("^11\\.Alimenta", c$nome))  sg11_id <- c$id
}
cat(sprintf("IBGE T7060: grupo 1 = id=%s ; subgrupo 11 = id=%s\n", g1_id, sg11_id))

# Pega ambos
fetch_ibge_cat <- function(catid) {
  url <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/7060/periodos/202001-202312/variaveis/63?localidades=N1[all]&classificacao=315[%s]", catid)
  raw <- fromJSON(content(GET(url, timeout(60)), "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  out <- list()
  for (item in raw[[1]]$resultados) {
    for (s in item$series) {
      for (p in names(s$serie)) {
        out[[length(out)+1]] <- data.frame(periodo = p, valor = as.numeric(s$serie[[p]]),
                                            stringsAsFactors = FALSE)
      }
    }
  }
  do.call(rbind, out)
}

ibge_g1   <- fetch_ibge_cat(g1_id)
ibge_sg11 <- fetch_ibge_cat(sg11_id)
ibge_g1$date   <- as.Date(paste0(substr(ibge_g1$periodo,1,4), "-", substr(ibge_g1$periodo,5,6), "-01"))
ibge_sg11$date <- as.Date(paste0(substr(ibge_sg11$periodo,1,4), "-", substr(ibge_sg11$periodo,5,6), "-01"))

cmp1 <- merge(bcb_1635, ibge_g1[, c("date","valor")],   by="date")
cmp2 <- merge(bcb_1635, ibge_sg11[, c("date","valor")], by="date")
cat(sprintf("\n=== TESTE 1: SGS 1635 == IBGE grupo 1 (Alimentação e bebidas) ?\n"))
cat(sprintf("    n=%d   mean|d|=%.4f   max|d|=%.4f   corr=%.4f\n",
            nrow(cmp1), mean(abs(cmp1$value - cmp1$valor)),
            max(abs(cmp1$value - cmp1$valor)),
            cor(cmp1$value, cmp1$valor)))
cat(sprintf("=== TESTE 2: SGS 1635 == IBGE subgrupo 11 (Alim. domicílio) ?\n"))
cat(sprintf("    n=%d   mean|d|=%.4f   max|d|=%.4f   corr=%.4f\n",
            nrow(cmp2), mean(abs(cmp2$value - cmp2$valor)),
            max(abs(cmp2$value - cmp2$valor)),
            cor(cmp2$value, cmp2$valor)))

cat("\n=== Lado-a-lado primeiros meses ===\n")
cat("date         SGS1635   IBGE-grupo1   IBGE-sub11\n")
m_all <- merge(cmp1, ibge_sg11[, c("date","valor")], by="date")
names(m_all) <- c("date","sgs1635","ibge_g1","ibge_sg11")
for (i in 1:12) cat(sprintf("%s   %+7.3f      %+7.3f       %+7.3f\n",
                             format(m_all$date[i]), m_all$sgs1635[i],
                             m_all$ibge_g1[i], m_all$ibge_sg11[i]))
