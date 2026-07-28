#!/usr/bin/env Rscript
# Versão enxuta do probe. Só ranges plausíveis, paralelizando o que dá.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

fetch_bcb <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json&dataInicial=01/01/2020&dataFinal=31/12/2024", code)
  r <- tryCatch(GET(url, timeout(10)), error = function(e) NULL)
  if (is.null(r) || status_code(r) != 200) return(NULL)
  txt <- content(r, "text", encoding = "UTF-8")
  if (nchar(txt) < 10 || substr(txt, 1, 1) == "<") return(NULL)
  raw <- tryCatch(fromJSON(txt), error = function(e) NULL)
  if (is.null(raw) || !is.data.frame(raw) || nrow(raw) < 24) return(NULL)
  data.frame(date = as.Date(raw$data, format = "%d/%m/%Y"),
             value = as.numeric(raw$valor))
}

df <- read.csv("data/ipca15_pareto_recon.csv", stringsAsFactors = FALSE)
df$date <- as.Date(df$date)
T_IN  <- df[df$category_code == "alim_in_natura",  c("date","value")]
T_SE  <- df[df$category_code == "alim_semi_elab",  c("date","value")]
T_IND <- df[df$category_code == "alim_industr",    c("date","value")]

# Ranges mais focados. Códigos IPCA conhecidos clusters: 11xxx, 16xxx, 27xxx.
RANGES <- c(seq(27800, 27870), seq(11420, 11450), seq(16100, 16130),
            seq(1640, 1670), seq(4445, 4470))
RANGES <- unique(RANGES)
cat(sprintf("Sondando %d códigos\n", length(RANGES)))

check_one <- function(code) {
  bcb <- fetch_bcb(code)
  if (is.null(bcb)) return(NULL)
  result <- list()
  for (nm in c("IN","SE","IND")) {
    tgt <- list(IN=T_IN, SE=T_SE, IND=T_IND)[[nm]]
    m <- merge(bcb, tgt, by = "date", suffixes = c(".bcb",".ibge"))
    if (nrow(m) < 12 || sd(m$value.bcb)==0) next
    cc <- cor(m$value.bcb, m$value.ibge)
    if (!is.na(cc) && cc > 0.85) {
      d <- m$value.bcb - m$value.ibge
      result[[length(result)+1]] <- sprintf(
        "  SGS %d  vs alim_%-3s : n=%d corr=%.4f mean|d|=%.4f sd_bcb=%.2f sd_ibge=%.2f",
        code, nm, nrow(m), cc, mean(abs(d)), sd(m$value.bcb), sd(m$value.ibge))
    }
  }
  paste(result, collapse = "\n")
}

hits <- character(0)
for (i in seq_along(RANGES)) {
  code <- RANGES[i]
  if (i %% 25 == 0) cat(sprintf("[%d/%d] testado até %d... %d hits\n", i, length(RANGES), code, length(hits)))
  r <- check_one(code)
  if (length(r) && nchar(r) > 0) hits <- c(hits, r)
}

cat(sprintf("\n=== HITS (corr > 0.85): %d ===\n", length(hits)))
for (h in hits) cat(h, "\n")
