#!/usr/bin/env Rscript
# _probe_sidra_history.R — descobre até onde IBGE/SIDRA publica V63 (variação)
# e V66 (peso) por subitem do IPCA. Sem V66 não dá pra reconstruir as classes.
#
# Tabelas conhecidas / hipóteses:
#   T7060 — POF 2017-2018, 2020-01 → atual (já usado)
#   T1419 — POF 2008-2009, ~2012-01 → 2019-12 (V63 + V66 conhecidos)
#   T2938 — variante T1419 (?)
#   T7062 — IPCA POF 2017-2018 com mais variáveis
#   T655  — POF 2002-2003, 2006-07 → 2011-12 (sem V66 segundo comentário)
#   T118  — IPCA antigo
#   T2937 — variante histórica

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

# Probe SIDRA metadata: /metadados/<tabela> retorna variáveis disponíveis,
# período mín/máx, classificações etc.
probe_meta <- function(tbl) {
  url <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/metadados", tbl)
  r <- tryCatch(GET(url, timeout(60)), error = function(e) NULL)
  if (is.null(r)) return(list(tbl = tbl, ok = FALSE, msg = "timeout"))
  if (status_code(r) != 200) return(list(tbl = tbl, ok = FALSE, msg = sprintf("HTTP %d", status_code(r))))
  raw <- tryCatch(fromJSON(content(r, "text", encoding = "UTF-8")), error = function(e) NULL)
  if (is.null(raw)) return(list(tbl = tbl, ok = FALSE, msg = "parse-fail"))
  list(tbl = tbl, ok = TRUE, raw = raw)
}

cat("Sondando metadados das tabelas SIDRA IPCA:\n")
TABS <- c(7060, 7062, 7063, 1419, 2938, 2937, 655, 118, 1737, 1736)
metas <- list()
for (t in TABS) {
  m <- probe_meta(t)
  if (!m$ok) {
    cat(sprintf("  T%-5d  FAIL %s\n", t, m$msg))
    next
  }
  metas[[as.character(t)]] <- m$raw
  vars <- m$raw$variaveis
  has_v63 <- 63 %in% vars$id
  has_v66 <- 66 %in% vars$id
  per_min <- m$raw$periodicidade$inicio
  per_max <- m$raw$periodicidade$fim
  nome <- substr(m$raw$nome, 1, 70)
  cat(sprintf("  T%-5d  %s..%s  V63=%s V66=%s  %s\n",
              t, per_min, per_max,
              if (has_v63) "✓" else "✗",
              if (has_v66) "✓" else "✗",
              nome))
}

cat("\nDetalhes das que têm V66 (necessário pra reconstrução):\n")
for (t_str in names(metas)) {
  m <- metas[[t_str]]
  if (!(66 %in% m$variaveis$id)) next
  cat(sprintf("\n  T%s — %s\n", t_str, m$nome))
  cat(sprintf("    Período: %s → %s\n", m$periodicidade$inicio, m$periodicidade$fim))
  cat(sprintf("    Variáveis com 'peso' no nome:\n"))
  for (i in seq_len(nrow(m$variaveis))) {
    nm <- m$variaveis$nome[i]
    if (grepl("peso|variação|índice", nm, ignore.case = TRUE)) {
      cat(sprintf("      V%-4d  %s (%s)\n",
                  m$variaveis$id[i], nm, m$variaveis$unidade[i]))
    }
  }
  # Classificações (queremos a 315 = geral/grupos/subgrupos/itens/subitens)
  if (!is.null(m$classificacoes) && length(m$classificacoes) > 0) {
    cls_ids <- m$classificacoes$id
    cat(sprintf("    Classificações: %s\n", paste(cls_ids, collapse = ", ")))
    if (315 %in% cls_ids) cat("    ✓ tem cls 315 (subitens IPCA)\n")
  }
}
