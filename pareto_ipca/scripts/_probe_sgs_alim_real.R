#!/usr/bin/env Rscript
# _probe_sgs_alim_real.R — descobre os SGS reais para alim_in/se/ind.
# Estratégia: varre ranges plausíveis no SGS BCB, e pra cada série com
# dados, mede correlação contra nossas alim_in_natura / alim_semi_elab /
# alim_industr (que seguem Tab.5). Candidato verdadeiro deve ter
# corr > 0.95 com a série certa e magnitude compatível (sd ~ similar).

suppressPackageStartupMessages({ library(httr); library(jsonlite) })
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

# Janela curta pra ser rápido (precisa só caracterizar bem).
fetch_bcb <- function(code, ini = "01/01/2020", fim = "31/12/2024") {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json&dataInicial=%s&dataFinal=%s",
                 code, ini, fim)
  r <- tryCatch(GET(url, timeout(15)), error = function(e) NULL)
  if (is.null(r) || status_code(r) != 200) return(NULL)
  txt <- content(r, "text", encoding = "UTF-8")
  if (nchar(txt) < 10 || substr(txt, 1, 1) == "<") return(NULL)
  raw <- tryCatch(fromJSON(txt), error = function(e) NULL)
  if (is.null(raw) || !is.data.frame(raw) || nrow(raw) == 0) return(NULL)
  data.frame(date = as.Date(raw$data, format = "%d/%m/%Y"),
             value = as.numeric(raw$valor))
}

df <- read.csv("data/ipca_pareto_recon.csv", stringsAsFactors = FALSE)
df$date <- as.Date(df$date)
targets <- list(
  alim_in_natura  = df[df$category_code == "alim_in_natura",  c("date","value")],
  alim_semi_elab  = df[df$category_code == "alim_semi_elab",  c("date","value")],
  alim_industr    = df[df$category_code == "alim_industr",    c("date","value")]
)

# Ranges plausíveis: próximos a 27864 (alim_dom), próximos a 4449 (admin),
# IPCA "novos" 27xxx e blocos comuns 1500-1700, 4400-4500, 27800-28000.
RANGES <- c(
  # Vizinhança imediata de códigos IPCA conhecidos
  seq(27800, 27900),
  seq(11400, 11440),
  seq(10800, 10860),
  seq(4440, 4480),
  seq(4460, 4475),
  seq(1700, 1800),   # depois do 1635-1639 (grupos), pode ter subgrupos
  seq(16100, 16140),
  seq(28000, 28050)
)
RANGES <- unique(RANGES)
cat(sprintf("Sondando %d códigos SGS contra alim_in/se/ind (corr > 0.90 ⇒ candidato)\n",
            length(RANGES)))

hits <- list()
for (code in RANGES) {
  bcb <- fetch_bcb(code)
  if (is.null(bcb) || nrow(bcb) < 24) next
  for (tgt_name in names(targets)) {
    tgt <- targets[[tgt_name]]
    m <- merge(bcb, tgt, by = "date", suffixes = c(".bcb",".ibge"))
    if (nrow(m) < 24) next
    if (sd(m$value.bcb) == 0 || sd(m$value.ibge) == 0) next
    cc <- cor(m$value.bcb, m$value.ibge)
    if (is.na(cc)) next
    if (cc > 0.90) {
      d <- m$value.bcb - m$value.ibge
      hits[[length(hits)+1]] <- data.frame(
        sgs = code, target = tgt_name, n = nrow(m),
        corr = cc, mean_abs_d = mean(abs(d)), max_abs_d = max(abs(d)),
        sd_bcb = sd(m$value.bcb), sd_ibge = sd(m$value.ibge),
        stringsAsFactors = FALSE)
    }
  }
}
if (length(hits)) {
  res <- do.call(rbind, hits)
  res <- res[order(-res$corr), ]
  cat("\nCandidatos (corr > 0.90 contra uma das nossas séries):\n")
  print(res, row.names = FALSE)
} else {
  cat("\nNenhum SGS na varredura bate (corr > 0.90) com alim_in/se/ind.\n")
}
