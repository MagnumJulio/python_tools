#!/usr/bin/env Rscript
# _probe_pof_weight_gap.R — quanto PESO da T2938 / T1419 fica sem classificação
# se aplicar nossa máscara atual? Decide se dá pra rodar IBGE-only com a mask
# existente (gap pequeno) ou se precisa expandir a máscara (gap material).

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

MASK_PATH <- Sys.getenv("MASK_PATH", unset = "scripts/ipca_masks/classificacao.csv")
cat(sprintf("MÁSCARA: %s\n\n", MASK_PATH))
mask <- read.csv(MASK_PATH, stringsAsFactors = FALSE)
mask$cod_ibge <- as.character(mask$cod_ibge)
mask_codes <- unique(mask$cod_ibge)

fetch_var <- function(tbl, periodo, var) {
  url <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=315[all]",
                 tbl, periodo, var)
  r <- GET(url, timeout(180))
  if (status_code(r) != 200) stop(sprintf("T%d V%d HTTP %d", tbl, var, status_code(r)))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  out <- list()
  for (var_node in raw) for (res_node in var_node$resultados) {
    cls <- res_node$classificacoes[[1]]
    cat_id   <- names(cls$categoria)[[1]]
    cat_nome <- cls$categoria[[1]]
    for (s in res_node$series) {
      per_keys <- names(s$serie)
      per_vals <- as.character(unlist(s$serie))
      for (k in seq_along(per_keys)) {
        out[[length(out) + 1]] <- list(periodo = per_keys[[k]],
                                       cat_id = cat_id, cat_nome = cat_nome,
                                       valor = per_vals[[k]])
      }
    }
  }
  data.frame(
    periodo  = sapply(out, function(x) x$periodo),
    cat_nome = sapply(out, function(x) x$cat_nome),
    valor    = suppressWarnings(as.numeric(sapply(out, function(x) x$valor))),
    stringsAsFactors = FALSE
  )
}
extrair_cod <- function(nm) {
  pref <- sub("^([0-9]+)\\..*$", "\\1", nm)
  ifelse(pref == nm, NA_character_, pref)
}

PROBES <- list(
  list(tbl = 2938, per = "200607", label = "T2938 / 2006-07"),
  list(tbl = 1419, per = "201201", label = "T1419 / 2012-01"),
  list(tbl = 7060, per = "202001", label = "T7060 / 2020-01 (controle)")
)

cat("Análise de cobertura de PESO da máscara vs SIDRA por POF:\n\n")
for (p in PROBES) {
  cat(sprintf("[%s]\n", p$label))
  pesos <- fetch_var(p$tbl, p$per, 66)
  pesos$cod <- extrair_cod(pesos$cat_nome)
  subi <- pesos[!is.na(pesos$cod) & nchar(pesos$cod) == 7, ]
  total <- sum(subi$valor, na.rm = TRUE)
  subi$in_mask <- subi$cod %in% mask_codes
  peso_ok   <- sum(subi$valor[subi$in_mask],  na.rm = TRUE)
  peso_gap  <- sum(subi$valor[!subi$in_mask], na.rm = TRUE)
  cat(sprintf("  subitens:     %d  (em mask: %d, fora: %d)\n",
              nrow(subi), sum(subi$in_mask), sum(!subi$in_mask)))
  cat(sprintf("  soma pesos:   %.4f  (esperado ~100)\n", total))
  cat(sprintf("  peso em mask: %.4f (%.2f%%)\n", peso_ok, 100*peso_ok/total))
  cat(sprintf("  peso fora:    %.4f (%.2f%%)\n", peso_gap, 100*peso_gap/total))
  if (peso_gap > 0) {
    fora <- subi[!subi$in_mask, ]
    fora <- fora[order(-fora$valor), ]
    cat("  top-15 não-classificados (peso):\n")
    for (i in seq_len(min(15, nrow(fora)))) {
      cat(sprintf("    %s  %6.4f%%  %s\n",
                  fora$cod[i], fora$valor[i],
                  substr(fora$cat_nome[i], 1, 60)))
    }
  }
  cat("\n")
}
