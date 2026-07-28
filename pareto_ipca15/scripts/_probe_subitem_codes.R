#!/usr/bin/env Rscript
# _probe_subitem_codes.R — compara códigos de subitem entre POFs.
# Risco: códigos podem ter mudado entre T2938 (POF 2002-03), T1419 (POF 2008-09)
# e T7060 (POF 2017-18). Se mudaram, precisa de máscara por POF ou mapeamento.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

mask <- read.csv("scripts/ipca_masks/classificacao.csv", stringsAsFactors = FALSE)
mask$cod_ibge <- as.character(mask$cod_ibge)
mask_codes <- sort(unique(mask$cod_ibge))
cat(sprintf("Máscara: %d subitens\n\n", length(mask_codes)))

# Fetch igual reconstruct_ipca.R, mas só extrai cat_id/cat_nome (não precisa valor)
fetch_codes <- function(tbl, periodo) {
  url <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/63?localidades=N1[all]&classificacao=315[all]",
                 tbl, periodo)
  r <- GET(url, timeout(180))
  if (status_code(r) != 200) stop(sprintf("T%d %s HTTP %d", tbl, periodo, status_code(r)))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  out <- list()
  for (var_node in raw) {
    for (res_node in var_node$resultados) {
      cls <- res_node$classificacoes[[1]]
      cat_id   <- names(cls$categoria)[[1]]
      cat_nome <- cls$categoria[[1]]
      out[[length(out) + 1]] <- list(cat_id = cat_id, cat_nome = cat_nome)
    }
  }
  data.frame(
    cat_id   = sapply(out, function(x) x$cat_id),
    cat_nome = sapply(out, function(x) x$cat_nome),
    stringsAsFactors = FALSE
  )
}

# cod_ibge extraído do prefixo do nome (mesma lógica do reconstruct)
extrair_cod <- function(nome) {
  pref <- sub("^([0-9]+)\\..*$", "\\1", nome)
  ifelse(pref == nome, NA_character_, pref)
}

PROBES <- list(
  list(tbl = 2938, per = "200607", label = "T2938 (POF 2002-03), 1º mês"),
  list(tbl = 1419, per = "201201", label = "T1419 (POF 2008-09), 1º mês"),
  list(tbl = 7060, per = "202001", label = "T7060 (POF 2017-18), 1º mês")
)

results <- list()
for (p in PROBES) {
  cat(sprintf("[%s]\n", p$label))
  df <- tryCatch(fetch_codes(p$tbl, p$per),
                 error = function(e) { cat(sprintf("  ERRO: %s\n", e$message)); NULL })
  if (is.null(df)) { cat("\n"); next }
  df$cod <- extrair_cod(df$cat_nome)
  subi <- unique(df$cod[!is.na(df$cod) & nchar(df$cod) == 7])
  cat(sprintf("  categorias totais: %d  |  subitens (cod 7-dig): %d\n",
              nrow(df), length(subi)))
  in_mask  <- intersect(mask_codes, subi)
  miss_mask <- setdiff(mask_codes, subi)   # mask diz que existe, tab não tem
  miss_tab  <- setdiff(subi, mask_codes)   # tab tem, mask não classifica
  cat(sprintf("  ∩ mask:                   %d  (%.1f%% da mask)\n",
              length(in_mask), 100*length(in_mask)/length(mask_codes)))
  cat(sprintf("  mask sem-correspondência: %d  (subitens da mask ausentes na tab)\n",
              length(miss_mask)))
  cat(sprintf("  tab sem-classificação:    %d  (subitens da tab que mask não classifica)\n",
              length(miss_tab)))
  if (length(miss_mask) > 0)
    cat(sprintf("  ex (mask→sem-tab): %s\n",
                paste(head(miss_mask, 10), collapse = ", ")))
  if (length(miss_tab) > 0) {
    nms <- df$cat_nome[match(head(miss_tab, 6), df$cod)]
    cat(sprintf("  ex (tab→sem-mask):\n%s\n",
                paste("    ", nms, collapse = "\n")))
  }
  results[[p$label]] <- subi
  cat("\n")
}

# Sobreposição entre as 3 tabelas
if (length(results) == 3) {
  cat("======================================================================\n")
  cat("Sobreposição entre as 3 tabelas (intersection):\n")
  cat("======================================================================\n")
  s1 <- results[[1]]; s2 <- results[[2]]; s3 <- results[[3]]
  i12 <- intersect(s1, s2); i23 <- intersect(s2, s3); i123 <- intersect(i12, s3)
  cat(sprintf("  T2938:                 %d subitens\n", length(s1)))
  cat(sprintf("  T1419:                 %d subitens\n", length(s2)))
  cat(sprintf("  T7060:                 %d subitens\n", length(s3)))
  cat(sprintf("  T2938 ∩ T1419:         %d (∆ %d→%d)\n", length(i12),
              length(setdiff(s1, s2)), length(setdiff(s2, s1))))
  cat(sprintf("  T1419 ∩ T7060:         %d (∆ %d→%d)\n", length(i23),
              length(setdiff(s2, s3)), length(setdiff(s3, s2))))
  cat(sprintf("  T2938 ∩ T1419 ∩ T7060: %d\n", length(i123)))
  cat(sprintf("  mask ∩ todas:          %d (%.1f%% da mask viável retroativamente)\n",
              length(intersect(mask_codes, i123)),
              100*length(intersect(mask_codes, i123))/length(mask_codes)))
}
