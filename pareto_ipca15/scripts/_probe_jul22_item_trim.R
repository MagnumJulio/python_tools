# Por que MA_item diverge em mar/jul/ago/2022? Inspeciona o trim por item nesses meses.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c("202203","202207","202208","202112")  # 3 bad meses + 1 good (controle)
BCB_MA <- c("202203"=1.45,"202207"=-0.07,"202208"=0.05,"202112"=0.67)

SIDRA_AGG <- 7060L; SIDRA_CLS <- 315L

url_str <- function(var, perds) {
  sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=%d[all]",
          SIDRA_AGG, paste(perds, collapse=","), var, SIDRA_CLS)
}
fetch_long <- function(var) {
  r <- GET(url_str(var, PERIODOS), timeout(120))
  raw <- fromJSON(content(r, "text", encoding="UTF-8"), simplifyDataFrame=FALSE)
  rows <- list()
  for (vn in raw) for (rn in vn$resultados) {
    cls <- rn$classificacoes[[1]]
    for (s in rn$series) {
      pk <- names(s$serie); pv <- as.character(unlist(s$serie))
      for (k in seq_along(pk)) rows[[length(rows)+1]] <- list(
        periodo=pk[k], cat_nome=cls$categoria[[1]], valor=pv[k])
    }
  }
  d <- data.frame(periodo=sapply(rows,`[[`,"periodo"),
                  cat_nome=sapply(rows,`[[`,"cat_nome"),
                  valor=suppressWarnings(as.numeric(sapply(rows,`[[`,"valor"))),
                  stringsAsFactors=FALSE)
  d$cod <- sub("^([0-9]+)\\..*$","\\1",d$cat_nome)
  d[!is.na(d$cod) & nchar(d$cod) == 4, ]  # itens (4 digitos)
}

cat("[1] Fetch V63 + V66 nivel ITEM...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"
m <- merge(v63[, c("periodo","cod","cat_nome","var_mm")],
           v66[, c("periodo","cod","peso_mm")], by=c("periodo","cod"))

for (per in PERIODOS) {
  cat(sprintf("\n========== %s (BCB MA = %.2f) ==========\n", per, BCB_MA[per]))
  s <- m[m$periodo == per, ]
  s <- s[!is.na(s$var_mm) & !is.na(s$peso_mm) & s$peso_mm > 0, ]
  s <- s[order(s$var_mm), ]
  tp <- sum(s$peso_mm)
  s$cum_end <- cumsum(s$peso_mm) / tp
  s$cum_start <- s$cum_end - s$peso_mm / tp
  s$status <- ifelse(s$cum_end <= 0.20, "CUT_LOW",
                ifelse(s$cum_start >= 0.80, "CUT_HIGH", "KEEP"))
  s$cat_short <- substr(s$cat_nome, 1, 50)

  cat(sprintf("Total itens: %d, Σpeso: %.2f\n", nrow(s), tp))
  cat("\nLOWER TAIL (cortados):\n")
  cut_lo <- s[s$status == "CUT_LOW", c("cod","cat_short","var_mm","peso_mm","cum_end")]
  print(cut_lo, row.names=FALSE)

  cat("\nKEEP (no meio, entram no MA):\n")
  keep <- s[s$status == "KEEP", c("cod","cat_short","var_mm","peso_mm","cum_start","cum_end")]
  cat(sprintf("  N=%d, Σpeso=%.2f, mean ponderada=%+.4f\n",
              nrow(keep), sum(keep$peso_mm), sum(keep$var_mm * keep$peso_mm) / sum(keep$peso_mm)))
  # Top 5 + bottom 5 dos KEEP
  cat("  Top 5 (mais positivos no KEEP):\n")
  print(tail(keep, 5), row.names=FALSE)
  cat("  Bottom 5 (mais negativos no KEEP):\n")
  print(head(keep, 5), row.names=FALSE)

  cat("\nUPPER TAIL (cortados):\n")
  cut_hi <- s[s$status == "CUT_HIGH", c("cod","cat_short","var_mm","peso_mm","cum_start")]
  print(cut_hi, row.names=FALSE)
}
