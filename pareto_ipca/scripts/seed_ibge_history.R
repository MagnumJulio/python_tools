#!/usr/bin/env Rscript
# seed_ibge_history.R
#
# Reconstrói TODAS as 20 séries derivadas do IPCA 100% via IBGE/SIDRA, fazendo
# stitching das 3 tabelas que publicam V63 (variação) + V66 (peso) por subitem:
#
#   T2938 — POF 2002-03  →  2006-07 a 2011-12  (máscara extended)
#   T1419 — POF 2008-09  →  2012-01 a 2019-12  (máscara extended)
#   T7060 — POF 2017-18  →  2020-01 a atual    (máscara base)
#
# Cobertura final: 2006-07 → atual (~20 anos) com metodologia única (Laspeyres
# IBGE-only). Pré-2006-07: IBGE não publica V66 (pesos por subitem); gap real.
#
# Substitui o caminho de produção que usava BCB SGS (seed_pareto_history.R).
# BCB permanece SÓ como referência de validação nos scripts de auditoria
# (_audit_*.R). Conforme decisão: "tudo tem que vir do IBGE; BCB é só pra
# conferir o que foi montado pelo IBGE."
#
# Uso:
#   cd pareto_ipca
#   Rscript scripts/seed_ibge_history.R                  # janela completa default
#   Rscript scripts/seed_ibge_history.R --skip-current   # só 2006-07 → 2019-12
#                                                          (não roda T7060)

suppressPackageStartupMessages({})

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

args <- commandArgs(trailingOnly = TRUE)
SKIP_CURRENT <- "--skip-current" %in% args

MASK_BASE     <- "scripts/ipca_masks/classificacao.csv"
MASK_EXTENDED <- "scripts/ipca_masks/classificacao_extended.csv"
RECON_SCRIPT  <- "scripts/reconstruct_ipca.R"

if (!file.exists(MASK_EXTENDED)) {
  stop("Máscara extended não encontrada: ", MASK_EXTENDED,
       "\nNecessária pra POFs antigas (subitens extintos em POF 2017-18).")
}
if (!file.exists(RECON_SCRIPT)) stop("Script não encontrado: ", RECON_SCRIPT)

# Último período: mês passado (mês corrente raramente publicado pelo IBGE no
# dia 1).
hoje <- Sys.Date()
ref_prev <- seq(hoje, by = "-1 month", length.out = 2)[2]
PER_LATEST <- as.integer(format(ref_prev, "%Y%m"))

WINDOWS <- list(
  list(tbl = 2938L, ini = 200607L, fim = 201112L, mask = MASK_EXTENDED,
       label = "T2938 / POF 2002-03"),
  list(tbl = 1419L, ini = 201201L, fim = 201912L, mask = MASK_EXTENDED,
       label = "T1419 / POF 2008-09"),
  list(tbl = 7060L, ini = 202001L, fim = PER_LATEST, mask = MASK_BASE,
       label = "T7060 / POF 2017-18")
)
if (SKIP_CURRENT) WINDOWS <- WINDOWS[1:2]

cat("\n=========================================================\n")
cat(" seed_ibge_history.R — stitching 3 tabelas SIDRA IPCA\n")
cat("=========================================================\n")
for (w in WINDOWS) {
  cat(sprintf("  %-20s  %d → %d  máscara=%s\n",
              w$label, w$ini, w$fim, basename(w$mask)))
}
cat("\n")

run_one <- function(w) {
  cat(sprintf("\n--- [%s] janela %d → %d ---\n", w$label, w$ini, w$fim))
  # Env vars novas pro subprocesso (não polui o atual)
  Sys.setenv(SIDRA_AGG_ID        = as.character(w$tbl))
  Sys.setenv(MASK_CLASS_PATH_OVR = w$mask)
  # Roda o reconstruct via Rscript (processo isolado, mesma R version).
  # Capture exit code; aborta se falhar.
  rc <- system2("Rscript",
                args = c(RECON_SCRIPT, as.character(w$ini), as.character(w$fim)),
                stdout = "", stderr = "")
  Sys.unsetenv("SIDRA_AGG_ID")
  Sys.unsetenv("MASK_CLASS_PATH_OVR")
  if (rc != 0) {
    stop(sprintf("[%s] reconstruct_ipca.R retornou exit=%d", w$label, rc))
  }
  cat(sprintf("--- [%s] OK ---\n", w$label))
}

t_start <- Sys.time()
for (w in WINDOWS) run_one(w)
t_end <- Sys.time()

cat(sprintf("\n=========================================================\n"))
cat(sprintf(" Concluído em %.1fs\n", as.numeric(difftime(t_end, t_start, units = "secs"))))
cat(sprintf("=========================================================\n"))

PARETO_CSV <- "data/ipca_pareto_recon.csv"

# Pós-processamento: recalcular nucleo_medio a partir do CSV já costurado.
# Por que: cada Rscript do reconstruct_ipca roda isolado, e o DP tem warm-up
# (~6m) no início de cada janela. Logo nucleo_medio = rowMeans(EX0,EX3,MS,DP,P55)
# sai NA nas fronteiras T2938→T1419 (2012-01..06) e T1419→T7060 (2020-01..06),
# mesmo quando os 5 componentes já estão completos no CSV final (vindos do mês
# anterior da janela vizinha ou de runs prévias). Aqui sobrescrevemos o medio
# a partir do que está costurado, eliminando os buracos artificiais.
if (file.exists(PARETO_CSV)) {
  cat("\n[pós] Recalculando nucleo_medio a partir do CSV combinado...\n")
  dfp <- read.csv(PARETO_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
  dfp$date <- as.Date(dfp$date)
  comps <- c("nucleo_ex0", "nucleo_ex3", "nucleo_ms",
             "nucleo_dp", "nucleo_p55")
  comp_df <- dfp[dfp$category_code %in% comps,
                 c("date", "category_code", "value")]
  wide <- reshape(comp_df, idvar = "date", timevar = "category_code",
                  direction = "wide")
  val_cols <- paste0("value.", comps)
  falta <- setdiff(val_cols, names(wide))
  if (length(falta) > 0) {
    stop("Componentes do nucleo_medio ausentes no CSV: ",
         paste(falta, collapse = ", "))
  }
  novo <- data.frame(
    date          = wide$date,
    category_code = "nucleo_medio",
    value         = rowMeans(wide[, val_cols], na.rm = FALSE),
    stringsAsFactors = FALSE
  )
  novo <- novo[!is.na(novo$value), ]
  dfp <- dfp[dfp$category_code != "nucleo_medio", ]
  dfp <- rbind(dfp, novo)
  dfp <- dfp[order(dfp$date, dfp$category_code), ]
  write.csv(dfp, PARETO_CSV, row.names = FALSE, fileEncoding = "UTF-8")
  cat(sprintf("    OK. nucleo_medio: %d obs (%s → %s)\n",
              nrow(novo),
              format(min(novo$date)), format(max(novo$date))))
}

# Sanity check: resumo do CSV final
if (file.exists(PARETO_CSV)) {
  df <- read.csv(PARETO_CSV, stringsAsFactors = FALSE)
  df$date <- as.Date(df$date)
  cat(sprintf("\n%s — %d linhas\n", PARETO_CSV, nrow(df)))
  cat(sprintf("Janela: %s → %s\n", format(min(df$date)), format(max(df$date))))
  cat("\nCobertura por classe:\n")
  agg <- aggregate(date ~ category_code, data = df,
                   FUN = function(d) c(n = length(d),
                                       min = format(min(d), "%Y-%m"),
                                       max = format(max(d), "%Y-%m")))
  print(agg, row.names = FALSE)
}

cat("\nPróximo passo: Rscript scripts/build_pareto_indice.R\n")
