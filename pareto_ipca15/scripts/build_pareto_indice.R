#!/usr/bin/env Rscript
# build_pareto_indice.R
#
# Constrói número-índice das séries PARETO (administrados, livres,
# industriais, serviços, alim_domicilio, nucleo_ex0, nucleo_ex3, duraveis,
# semiduraveis, ndur_industr, servicos_subj, servicos_exsubj, alim_in_natura,
# alim_semi_elab, alim_industr, comerc, ncomerc, nucleo_ma, nucleo_ms,
# nucleo_dp) a partir do CSV de variação mensal
# `data/ipca15_pareto_recon.csv` (que já cobre 1991-01 → atual via seed BCB +
# reconstrução SIDRA).
#
# Fórmula: idx[t] = idx[t-1] × (1 + var/100), partindo de 100 em 1991-01,
# depois rescaled pra dez/1993=100 (mesma base do IPCA_INDICE/* existente —
# mantém comparabilidade entre as séries derivadas).
#
# Saída: data/ipca15_pareto_indice.csv (long: date, category_code, index)
#
# Uso: cd backend && Rscript scripts/build_pareto_indice.R

# Auto-cwd: se chamado via Rscript de qualquer pasta, descobre a raiz do projeto
# (pai de scripts/) e seta como cwd. Evita "no such file" por wd errado.
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

PARETO_VAR_CSV  <- "data/ipca15_pareto_recon.csv"
PARETO_IDX_CSV  <- "data/ipca15_pareto_indice.csv"
dir.create(dirname(PARETO_IDX_CSV), showWarnings = FALSE, recursive = TRUE)

if (!file.exists(PARETO_VAR_CSV)) {
  stop(sprintf("CSV de variação não existe: %s — rode seed_pareto_history.R + reconstruct_ipca.R primeiro",
               PARETO_VAR_CSV))
}

cat(sprintf("[1] Lendo %s...\n", PARETO_VAR_CSV))
src <- read.csv(PARETO_VAR_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
src$date <- as.Date(src$date)
cat(sprintf("    %d linhas, %d categorias, %s → %s\n",
            nrow(src), length(unique(src$category_code)),
            format(min(src$date)), format(max(src$date))))

build_idx <- function(df) {
  df <- df[order(df$date), ]
  df$index <- NA_real_
  df$index[1] <- 100
  for (i in 2:nrow(df)) {
    df$index[i] <- df$index[i-1] * (1 + df$value[i] / 100)
  }
  # Rescaling: tenta dez/2012 (primeira dez/ comum no recon IPCA-15 IBGE-only,
  # T1705 começa fev/2012) → fallback base 100 no 1º mês.
  ref_candidates <- list(
    list(date = as.Date("2012-12-01"), label = "dez/2012")
  )
  applied <- FALSE
  for (rc in ref_candidates) {
    ref <- df$index[df$date == rc$date]
    if (length(ref) == 1 && !is.na(ref) && ref > 0) {
      df$index <- df$index / ref * 100
      applied <- TRUE
      break
    }
  }
  if (!applied) {
    warning(sprintf("[%s] sem dez/2012; mantém base 100 em %s",
                    df$category_code[1], format(min(df$date), "%Y-%m")))
  }
  df
}

cat("\n[2] Construindo índices por classe...\n")
classes <- sort(unique(src$category_code))
out_list <- list()
for (cls in classes) {
  d <- src[src$category_code == cls, c("date", "category_code", "value")]
  d <- build_idx(d)
  ref_idx <- d$index[d$date == as.Date("2012-12-01")]
  last_idx <- tail(d$index, 1)
  cat(sprintf("    %-15s %d obs (%s → %s), dez/2012=%.2f, último=%.2f\n",
              cls, nrow(d), format(min(d$date), "%Y-%m"),
              format(max(d$date), "%Y-%m"),
              if (length(ref_idx) == 1) ref_idx else NA_real_,
              last_idx))
  out_list[[length(out_list) + 1]] <- d[, c("date", "category_code", "index")]
}

out <- do.call(rbind, out_list)
out$index <- round(out$index, 6)
out <- out[order(out$date, out$category_code), ]

cat(sprintf("\n[3] Escrevendo %s...\n", PARETO_IDX_CSV))
write.csv(out, PARETO_IDX_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("    %d linhas (%d classes; cobertura por classe varia)\n",
            nrow(out), length(classes)))
cat("    OK.\n")
