# Trim levels alternativos a nivel ITEM, com janela ampliada.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

# Janela longa: 2014-2024, varios meses para evitar conclusao baseada em 3 outliers
PERIODOS <- c()
for (y in 2014:2024) for (m in c("01","04","07","10")) PERIODOS <- c(PERIODOS, sprintf("%d%s", y, m))

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

cat("[1] Fetch V63 + V66 nivel ITEM (T7060 — janela 2020-01 em diante)...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"
m <- merge(v63[, c("periodo","cod","var_mm")], v66[, c("periodo","cod","peso_mm")], by=c("periodo","cod"))

trim <- function(vars, pesos, lo, up) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  vars <- vars[ok]; pesos <- pesos[ok]
  if (!length(vars)) return(NA_real_)
  ord <- order(vars); vars <- vars[ord]; pesos <- pesos[ord]
  tp <- sum(pesos); ce <- cumsum(pesos)/tp; cs <- ce - pesos/tp
  el <- pmax(cs,lo); eu <- pmin(ce,up); ov <- pmax(eu-el,0)
  if (sum(ov) <= 0) return(NA_real_)
  sum(vars*ov)/sum(ov)
}

# Fetch BCB SGS 11426 pra janela completa
cat("[2] Fetch BCB SGS 11426...\n")
r <- GET("https://api.bcb.gov.br/dados/serie/bcdata.sgs.11426/dados?formato=json", timeout(60))
bcb <- fromJSON(content(r,"text",encoding="UTF-8"), simplifyDataFrame=TRUE)
bcb$periodo <- format(as.Date(bcb$data, format="%d/%m/%Y"), "%Y%m")
bcb$valor <- as.numeric(bcb$valor)
bcb_map <- setNames(bcb$valor, bcb$periodo)

# Grid de trims, todos simetricos
trims <- list(c(0.20,0.80), c(0.25,0.75), c(0.30,0.70), c(0.15,0.85), c(0.10,0.90))
labs <- c("20/80","25/75","30/70","15/85","10/90")

# Tambem com pesos AO QUADRADO (penaliza items grandes)
# E com pesos sqrt (suaviza)
cat("\n[3] Stats por trim level (toda janela, item level):\n")
cat(sprintf("  %-8s %8s %8s %8s %8s %8s\n",
            "trim", "n", "mean|d|", "bias", "RMSE", "max|d|"))
for (i in seq_along(trims)) {
  diffs <- numeric()
  for (per in PERIODOS) {
    if (is.na(bcb_map[per])) next
    s <- m[m$periodo == per, ]
    if (!nrow(s)) next
    v <- trim(s$var_mm, s$peso_mm, trims[[i]][1], trims[[i]][2])
    if (is.na(v)) next
    diffs <- c(diffs, v - bcb_map[per])
  }
  cat(sprintf("  %-8s %8d %8.4f %+8.4f %8.4f %8.4f\n",
              labs[i], length(diffs), mean(abs(diffs)), mean(diffs),
              sqrt(mean(diffs^2)), max(abs(diffs))))
}

# Tambem: trim assimetrico
cat("\n[4] Trims assimetricos:\n")
trims2 <- list(c(0.10,0.80), c(0.15,0.80), c(0.20,0.85), c(0.25,0.85), c(0.10,0.85))
labs2 <- c("10/80","15/80","20/85","25/85","10/85")
for (i in seq_along(trims2)) {
  diffs <- numeric()
  for (per in PERIODOS) {
    if (is.na(bcb_map[per])) next
    s <- m[m$periodo == per, ]
    if (!nrow(s)) next
    v <- trim(s$var_mm, s$peso_mm, trims2[[i]][1], trims2[[i]][2])
    if (is.na(v)) next
    diffs <- c(diffs, v - bcb_map[per])
  }
  cat(sprintf("  %-8s %8d %8.4f %+8.4f %8.4f %8.4f\n",
              labs2[i], length(diffs), mean(abs(diffs)), mean(diffs),
              sqrt(mean(diffs^2)), max(abs(diffs))))
}
