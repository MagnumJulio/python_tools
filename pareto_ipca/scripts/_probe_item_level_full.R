# Validacao final: trim 20/80 a nivel ITEM vs BCB SGS 11426, TODOS os meses 2020-presente.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

# Todos os meses 2020-01 a 2026-04
PERIODOS <- c()
for (y in 2020:2026) {
  meses <- if (y == 2026) 1:4 else 1:12
  for (m in meses) PERIODOS <- c(PERIODOS, sprintf("%d%02d", y, m))
}

SIDRA_AGG <- 7060L; SIDRA_CLS <- 315L

url_str <- function(var, perds) {
  sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=%d[all]",
          SIDRA_AGG, paste(perds, collapse=","), var, SIDRA_CLS)
}
fetch_long <- function(var) {
  r <- GET(url_str(var, PERIODOS), timeout(180))
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
  d[!is.na(d$cod) & nchar(d$cod) == 4, ]
}

cat("[1] Fetch V63 + V66 nivel ITEM (T7060)...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"
m <- merge(v63[, c("periodo","cod","var_mm")], v66[, c("periodo","cod","peso_mm")], by=c("periodo","cod"))

trim <- function(vars, pesos, lo=0.20, up=0.80) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  vars <- vars[ok]; pesos <- pesos[ok]
  if (!length(vars)) return(NA_real_)
  ord <- order(vars); vars <- vars[ord]; pesos <- pesos[ord]
  tp <- sum(pesos); ce <- cumsum(pesos)/tp; cs <- ce - pesos/tp
  el <- pmax(cs,lo); eu <- pmin(ce,up); ov <- pmax(eu-el,0)
  if (sum(ov) <= 0) return(NA_real_)
  sum(vars*ov)/sum(ov)
}

cat("[2] Fetch BCB SGS 11426 (MA)...\n")
r <- GET("https://api.bcb.gov.br/dados/serie/bcdata.sgs.11426/dados?formato=json", timeout(60))
bcb <- fromJSON(content(r,"text",encoding="UTF-8"), simplifyDataFrame=TRUE)
bcb$periodo <- format(as.Date(bcb$data, format="%d/%m/%Y"), "%Y%m")
bcb$valor <- as.numeric(bcb$valor)
bcb_map <- setNames(bcb$valor, bcb$periodo)

cat("\n[3] Comparativo mes-a-mes (todos os meses T7060):\n")
cat(sprintf("  %-8s %8s %8s %+8s\n", "periodo", "ours", "BCB", "diff"))
diffs <- numeric()
worst <- list()
for (per in PERIODOS) {
  if (is.na(bcb_map[per])) next
  s <- m[m$periodo == per, ]
  if (!nrow(s)) next
  v <- trim(s$var_mm, s$peso_mm)
  if (is.na(v)) next
  d <- v - bcb_map[per]
  diffs <- c(diffs, d)
  if (abs(d) > 0.05) {
    worst[[length(worst)+1]] <- list(per=per, ours=v, bcb=bcb_map[per], diff=d)
  }
}

cat(sprintf("\n[STATS] n=%d, mean|d|=%.4f, bias=%+.4f, RMSE=%.4f, max|d|=%.4f\n",
            length(diffs), mean(abs(diffs)), mean(diffs), sqrt(mean(diffs^2)), max(abs(diffs))))
cat(sprintf("        Frac |d|<0.01pp: %.1f%%   |d|<0.005pp: %.1f%%   |d|>0.05pp: %.1f%%\n",
            100*mean(abs(diffs) < 0.01), 100*mean(abs(diffs) < 0.005), 100*mean(abs(diffs) > 0.05)))

if (length(worst)) {
  cat(sprintf("\n[WORST] %d meses com |d|>0.05pp:\n", length(worst)))
  for (w in worst) cat(sprintf("  %s ours=%+.4f bcb=%+.4f diff=%+.4f\n", w$per, w$ours, w$bcb, w$diff))
}
