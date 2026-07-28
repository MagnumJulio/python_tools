#!/usr/bin/env Rscript
# seed_ibge_history.R (pareto_ipca15)
#
# Reconstrói as séries derivadas do IPCA-15 100% via IBGE/SIDRA, fazendo
# stitching das 2 tabelas que publicam V63 (variação) + V66 (peso) por subitem:
#
#   T1705 — POF 2008-09  →  2012-02 a 2020-01  (máscara extended)
#   T7062 — POF 2017-18  →  2020-02 a atual    (máscara base)
#
# Cobertura final: 2012-02 → atual, com metodologia única (Laspeyres IBGE-only).
# Pré-2012-02: IBGE NÃO publica V66 IPCA-15 por subitem (T3065 é só headline
# histórico — sem classificação 315). Gap real, não há como reconstruir.
#
# BCB SGS pra IPCA-15: só o HEADLINE tem código (7478). Confirmado por
# sonda 2026-07-27 (`_probe_score.py` sobre ~230 SGS candidatos). O
# reconstruct_ipca.R seção [5] agora faz [5a] validação real headline vs SGS
# 7478 + [5b] diagnóstico do gap breakdowns vs SGS IPCA cheio. Rodar SEM
# `--no-bcb` em release day pra confirmar que o headline bate.
#
# Uso:
#   cd pareto_ipca15
#   Rscript scripts/seed_ibge_history.R                  # janela completa default
#   Rscript scripts/seed_ibge_history.R --skip-current   # só 2012-02 → 2020-01
#                                                          (não roda T7062)
#   Rscript scripts/seed_ibge_history.R --no-bcb         # pula rede BCB (dev local)

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
NO_BCB       <- "--no-bcb"       %in% args

MASK_BASE     <- "scripts/ipca_masks/classificacao.csv"
MASK_EXTENDED <- "scripts/ipca_masks/classificacao_extended.csv"
RECON_SCRIPT  <- "scripts/reconstruct_ipca.R"

if (!file.exists(MASK_EXTENDED)) {
  stop("Máscara extended não encontrada: ", MASK_EXTENDED,
       "\nNecessária pra POF 2008-09 (subitens extintos em POF 2017-18).")
}
if (!file.exists(RECON_SCRIPT)) stop("Script não encontrado: ", RECON_SCRIPT)

# Último período: mês passado (mês corrente raramente publicado pelo IBGE no
# dia 1). IPCA-15 é publicado ~dia 24 do mês de referência (adianta o IPCA
# cheio), então o mês "atual" às vezes já está disponível — mesmo assim,
# defaultamos pro mês anterior; usuário pode passar janela explícita.
hoje <- Sys.Date()
ref_prev <- seq(hoje, by = "-1 month", length.out = 2)[2]
PER_LATEST <- as.integer(format(ref_prev, "%Y%m"))

WINDOWS <- list(
  list(tbl = 1705L, ini = 201202L, fim = 202001L, mask = MASK_EXTENDED,
       label = "T1705 / POF 2008-09"),
  list(tbl = 7062L, ini = 202002L, fim = PER_LATEST, mask = MASK_BASE,
       label = "T7062 / POF 2017-18")
)
if (SKIP_CURRENT) WINDOWS <- WINDOWS[1]

cat("\n=========================================================\n")
cat(" seed_ibge_history.R — stitching 2 tabelas SIDRA IPCA-15\n")
cat("=========================================================\n")
for (w in WINDOWS) {
  cat(sprintf("  %-22s  %d → %d  máscara=%s\n",
              w$label, w$ini, w$fim, basename(w$mask)))
}
if (NO_BCB) cat("\n  --no-bcb: validação vs SGS desligada em todos os subprocessos\n")
cat("\n")

run_one <- function(w) {
  cat(sprintf("\n--- [%s] janela %d → %d ---\n", w$label, w$ini, w$fim))
  # Env vars novas pro subprocesso (não polui o atual)
  Sys.setenv(SIDRA_AGG_ID        = as.character(w$tbl))
  Sys.setenv(MASK_CLASS_PATH_OVR = w$mask)
  if (NO_BCB) Sys.setenv(SKIP_BCB_VALIDATION = "1")
  rc <- system2("Rscript",
                args = c(RECON_SCRIPT, as.character(w$ini), as.character(w$fim)),
                stdout = "", stderr = "")
  Sys.unsetenv("SIDRA_AGG_ID")
  Sys.unsetenv("MASK_CLASS_PATH_OVR")
  if (NO_BCB) Sys.unsetenv("SKIP_BCB_VALIDATION")
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

PARETO_CSV <- "data/ipca15_pareto_recon.csv"

# Pós-processamento: recalcular nucleo_medio a partir do CSV já costurado.
# Cada Rscript do reconstruct roda isolado, e o DP tem warm-up (~6m) no início
# de cada janela — nucleo_medio sai NA nas fronteiras T1705→T7062 (2020-02..07)
# mesmo com os 5 componentes já completos no CSV final. Aqui sobrescrevemos
# o medio a partir do que está costurado.
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
