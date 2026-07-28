# Testa se BCB usa V69 (peso estrutural POF) em vez de V66 (peso mensal) no MA.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c("202112", "202201", "202202", "202205", "202206")
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
    cat_id <- names(cls$categoria)[[1]]; cat_nome <- cls$categoria[[1]]
    for (s in rn$series) {
      pk <- names(s$serie); pv <- as.character(unlist(s$serie))
      for (k in seq_along(pk)) rows[[length(rows)+1]] <- list(
        periodo=pk[k], cat_nome=cat_nome, valor=pv[k])
    }
  }
  d <- data.frame(
    periodo=sapply(rows, `[[`, "periodo"),
    cat_nome=sapply(rows, `[[`, "cat_nome"),
    valor=suppressWarnings(as.numeric(sapply(rows, `[[`, "valor"))),
    stringsAsFactors=FALSE
  )
  d$cod <- sub("^([0-9]+)\\..*$", "\\1", d$cat_nome)
  d <- d[!is.na(d$cod) & nchar(d$cod) == 7, ]
  d
}

cat("[1] Fetch V63 (var), V66 (peso mensal), V69 (peso item POF)...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mensal"
v69 <- fetch_long(69); names(v69)[3] <- "peso_pof"

m <- merge(v63[, c("periodo","cod","var_mm")],
           v66[, c("periodo","cod","peso_mensal")], by=c("periodo","cod"))
m <- merge(m, v69[, c("periodo","cod","peso_pof")], by=c("periodo","cod"))

trim <- function(vars, pesos, lo=0.20, up=0.80) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  vars <- vars[ok]; pesos <- pesos[ok]
  if (!length(vars)) return(NA_real_)
  ord <- order(vars); vars <- vars[ord]; pesos <- pesos[ord]
  tp <- sum(pesos); ce <- cumsum(pesos)/tp; cs <- ce - pesos/tp
  el <- pmax(cs, lo); eu <- pmin(ce, up); ov <- pmax(eu-el, 0)
  if (sum(ov) <= 0) return(NA_real_)
  sum(vars * ov) / sum(ov)
}

# Tambem: aggregado simples ponderado
agg <- function(vars, pesos) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  sum(vars[ok]*pesos[ok])/sum(pesos[ok])
}

# E: alternative trim ranges
cat("\n[2] MA(20/80) com V66 vs V69; trim alternativos; IPCA full:\n")
cat(sprintf("  %-8s %10s %10s %10s %10s %10s %10s %10s\n",
            "periodo", "Σv66", "Σv69", "IPCAfull", "MA_v66", "MA_v69", "MA15_v69", "MA25_v69"))
for (per in PERIODOS) {
  s <- m[m$periodo == per, ]
  cat(sprintf("  %-8s %10.4f %10.4f %10.4f %10.4f %10.4f %10.4f %10.4f\n",
              per,
              sum(s$peso_mensal, na.rm=TRUE),
              sum(s$peso_pof, na.rm=TRUE),
              agg(s$var_mm, s$peso_mensal),
              trim(s$var_mm, s$peso_mensal),
              trim(s$var_mm, s$peso_pof),
              trim(s$var_mm, s$peso_pof, 0.15, 0.85),
              trim(s$var_mm, s$peso_pof, 0.25, 0.75)))
}

# Reference BCB (manual): pra calibrar visualmente
cat("\n[ref] BCB SGS 11426 (MA) nos meses-problema:\n")
cat("  202112: 0.6700\n  202201: 0.6800\n  202202: 0.7200\n  202205: 0.8900\n  202206: 0.7100\n")
