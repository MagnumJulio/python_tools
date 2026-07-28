#!/usr/bin/env Rscript
# seed_pareto_history.R — LEGADO (mantido por compat / referência cruzada)
#
# ⚠️  Este script foi SUPERADO por `seed_ibge_history.R` (2026-05-25).
#     A pipeline de produção agora é 100% IBGE-only via stitching de T2938
#     + T1419 + T7060 (cobertura 2006-07 → atual). BCB SGS é usado APENAS
#     em scripts de auditoria (`_audit_*.R`) para validar a recon.
#     Decisão registrada no CLAUDE.md, seção "Histórico de migração".
#
# Trade-off da troca:
#   - Perdeu cobertura 1991-01 → 2006-06 (IBGE não publica V66 pré-2006).
#   - Ganhou: metodologia única em toda janela, sem mistura de fontes,
#     alim_in/se/ind passam a ter definição consistente (sem gap pós-2020).
#
# Para usar este seed legado mesmo assim (ex: comparação retroativa contra
# BCB pré-2006, ou bootstrap rápido sem rodar 3 tabelas SIDRA):
#
# Preenche o histórico (1991-01 → 2019-12) das séries PARETO no CSV servido
# via source=PARETO, usando BCB SGS direto. O reconstruct_ipca.R cobre 2020-01
# → atual via reconstrução IBGE-direta (T7060 + V63 + V66).
#
# Por que: T7060 só publica de 2020-01 em diante. T1419/T2938 publicam V63+V66
# (dava pra reconstruir 2006-07 → 2019-12), mas o BCB já fez esse trabalho com
# qualidade indistinguível (nosso recon. erra ~0.003pp vs BCB). E T655 (1999-08
# → 2006-06) NÃO expõe V66 — então 1991-01 → 2006-06 SÓ daria por BCB. Pra
# consistência metodológica, fazemos seed inteiro do histórico via BCB.
#
# Política de merge: este script NUNCA sobrescreve períodos que já estão no
# CSV. Ele só adiciona o que está faltando. O reconstruct_ipca.R (passo [8])
# sobrescreve a janela recente (default 24 meses) — é a autoridade pra 2020+.
#
# Uso:
#   cd backend
#   Rscript scripts/seed_pareto_history.R              # 1991-01 → 2019-12
#   Rscript scripts/seed_pareto_history.R --until-now  # 1991-01 → último BCB

suppressPackageStartupMessages({
  library(httr)
  library(jsonlite)
})

# Auto-cwd: se chamado via Rscript de qualquer pasta, descobre a raiz do projeto
# (pai de scripts/) e seta como cwd. Evita "no such file" por wd errado.
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

# Carrega config de proxy se existir (rede institucional). Sem o arquivo
# (rodando em casa), este source vira no-op.
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

PARETO_BASE_CSV <- "data/ipca15_pareto_recon.csv"
dir.create(dirname(PARETO_BASE_CSV), showWarnings = FALSE, recursive = TRUE)

# Default cobre até 2019-12. Flag --until-now estende até o último período BCB
# disponível (útil pra bootstrap sem rodar reconstruct_ipca.R primeiro).
args <- commandArgs(trailingOnly = TRUE)
UNTIL_NOW <- "--until-now" %in% args
CUTOFF_DATE <- if (UNTIL_NOW) as.Date("9999-12-01") else as.Date("2019-12-01")

CLASSES <- list(
  list(code = "administrados",  sgs = 4449L,  label = "Administrados"),
  list(code = "livres",         sgs = 11428L, label = "Livres"),
  list(code = "industriais",    sgs = 27863L, label = "Industriais"),
  list(code = "servicos",       sgs = 10844L, label = "Serviços"),
  list(code = "alim_domicilio", sgs = 27864L, label = "Alim. domicílio"),
  list(code = "nucleo_ex0",     sgs = 11427L, label = "Núcleo EX0"),
  list(code = "nucleo_ex3",     sgs = 27839L, label = "Núcleo EX3"),
  list(code = "duraveis",       sgs = 10843L, label = "Bens duráveis"),
  list(code = "semiduraveis",   sgs = 10842L, label = "Bens semi-duráveis"),
  list(code = "nucleo_ma",      sgs = 11426L, label = "Núcleo MA (médias aparadas)"),
  list(code = "nucleo_ms",      sgs = 4466L,  label = "Núcleo MS (médias aparadas suavizado)"),
  list(code = "nucleo_dp",      sgs = 16122L, label = "Núcleo DP (dupla ponderação)"),
  # Adicionadas 2026-05-25 após auditoria `_audit_8_divergentes.R`:
  # comerc/ncomerc têm bias quase nulo vs recon IBGE (mean|d|≈0.12/0.28pp,
  # bias <0.02pp) — universo bate; BCB só aplica leve reprocessamento. Degrau
  # esperado em 2020-01 é <0.05pp, dentro do ruído de release.
  list(code = "comerc",         sgs = 4447L,  label = "Comercializáveis"),
  list(code = "ncomerc",        sgs = 4448L,  label = "Não-comercializáveis")
)
# OBS: as 6 séries abaixo continuam SEM seed BCB SGS — auditoria 2026-05-25
# (`_audit_8_divergentes.R`) mostrou dois grupos distintos:
#
#  (a) alim_in_natura/semi_elab/industr — BCB SGS 1635/1636/1637 têm UNIVERSO
#      divergente (regressão SGS_27864 ~ 1635+1636+1637 dá coef negativo em
#      1637, prova matemática de definição diferente). Bias estrutural ~0.4pp.
#      Emendar criaria degrau de ~1pp em 2020-01.
#
#  (b) ndur_industr / servicos_subj / servicos_exsubj — BCB NÃO publica SGS
#      direto de variação dessas séries. SGS 10841 é composite (ndur+alim_in+
#      alim_se) e nem o composite bate bem (corr=0.60). 27840/27841/4395 são
#      valores absolutos, não variação mensal. Sem fonte BCB, gap fica.
#
# Cobertura dessas 6 começa em 2020-01.
DROP_NO_SEED <- c("alim_in_natura","alim_semi_elab","alim_industr",
                  "ndur_industr","servicos_subj","servicos_exsubj")

fetch_bcb_sgs <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  r <- GET(url, timeout(120))
  if (status_code(r) != 200) stop(sprintf("BCB SGS %d falhou: HTTP %d", code, status_code(r)))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = TRUE)
  data.frame(
    date  = as.Date(raw$data, format = "%d/%m/%Y"),
    value = as.numeric(raw$valor),
    stringsAsFactors = FALSE
  )
}

cat(sprintf("[CFG] cutoff: %s%s\n",
            format(CUTOFF_DATE), if (UNTIL_NOW) " (--until-now)" else ""))

new_rows <- list()
for (cls in CLASSES) {
  cat(sprintf("[GET] SGS %d (%s)... ", cls$sgs, cls$code))
  df <- fetch_bcb_sgs(cls$sgs)
  df <- df[df$date <= CUTOFF_DATE, ]
  cat(sprintf("%d obs (%s → %s)\n", nrow(df),
              format(min(df$date), "%Y-%m"), format(max(df$date), "%Y-%m")))
  df$category_code <- cls$code
  new_rows[[length(new_rows) + 1]] <- df[, c("date", "category_code", "value")]
}
seed <- do.call(rbind, new_rows)

cat(sprintf("\n[SEED] total candidato: %d linhas (%d classes × ~%d meses)\n",
            nrow(seed), length(CLASSES), as.integer(nrow(seed) / length(CLASSES))))

# Merge não-sobrescrevente: só adiciona (date, category_code) ausentes.
if (file.exists(PARETO_BASE_CSV)) {
  existing <- read.csv(PARETO_BASE_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
  existing$date <- as.Date(existing$date)
  k_existing <- paste(existing$date, existing$category_code)
  k_seed     <- paste(seed$date, seed$category_code)
  seed_new <- seed[!k_seed %in% k_existing, ]
  combined <- rbind(existing, seed_new)
  cat(sprintf("[MERGE] existente: %d linhas | a adicionar: %d | overlap (preservado): %d\n",
              nrow(existing), nrow(seed_new), nrow(seed) - nrow(seed_new)))
} else {
  combined <- seed
  cat("[MERGE] arquivo inexistente; criando do zero.\n")
}

combined <- combined[order(combined$date, combined$category_code), ]
write.csv(combined, PARETO_BASE_CSV, row.names = FALSE, fileEncoding = "UTF-8")

cat(sprintf("\n[OK] %d linhas (%s → %s) em %s\n",
            nrow(combined),
            format(min(combined$date)), format(max(combined$date)),
            PARETO_BASE_CSV))

cat("\nResumo por classe:\n")
agg <- aggregate(date ~ category_code, data = combined,
                 FUN = function(d) c(n = length(d),
                                     min = format(min(d), "%Y-%m"),
                                     max = format(max(d), "%Y-%m")))
print(agg, row.names = FALSE)
