# Diagnostico do trimmed_mean em jan/2022 — por que MA diverge?
suppressPackageStartupMessages({
  library(httr); library(jsonlite)
})

PERIODOS <- c("202112", "202201", "202202", "202206")
SIDRA_AGG <- 7060L
SIDRA_CLS <- 315L

# Pega V63 (var) e V66 (peso) por subitem nos meses do problema
url_str <- function(var) {
  sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=%d[all]",
          SIDRA_AGG, paste(PERIODOS, collapse=","), var, SIDRA_CLS)
}

fetch_long <- function(var) {
  r <- GET(url_str(var), timeout(120))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  rows <- list()
  for (vn in raw) for (rn in vn$resultados) {
    cls <- rn$classificacoes[[1]]
    cod <- names(cls$categoria)[[1]]
    cat_nome <- cls$categoria[[1]]
    for (s in rn$series) {
      pk <- names(s$serie); pv <- as.character(unlist(s$serie))
      for (k in seq_along(pk)) rows[[length(rows)+1]] <- list(
        periodo=pk[k], cod=cod, cat_nome=cat_nome, valor=pv[k]
      )
    }
  }
  d <- data.frame(
    periodo=sapply(rows, `[[`, "periodo"),
    cod=sapply(rows, `[[`, "cod"),
    cat_nome=sapply(rows, `[[`, "cat_nome"),
    valor=suppressWarnings(as.numeric(sapply(rows, `[[`, "valor"))),
    stringsAsFactors=FALSE
  )
  d
}

cat("[1] Fetch V63 (variacao)...\n")
v <- fetch_long(63)
cat("[2] Fetch V66 (peso)...\n")
p <- fetch_long(66)

# Extrai cod IBGE (prefixo numerico do cat_nome) e filtra subitens (7 digitos)
extrair_cod <- function(nome) {
  pref <- sub("^([0-9]+)\\..*$", "\\1", nome)
  ifelse(pref == nome, NA_character_, pref)
}
v$cod <- extrair_cod(v$cat_nome)
p$cod <- extrair_cod(p$cat_nome)
v <- v[!is.na(v$cod) & nchar(v$cod) == 7, ]
p <- p[!is.na(p$cod) & nchar(p$cod) == 7, ]

names(v)[which(names(v)=="valor")] <- "var_mm"
names(p)[which(names(p)=="valor")] <- "peso_mm"
m <- merge(v[, c("periodo","cod","cat_nome","var_mm")],
           p[, c("periodo","cod","peso_mm")],
           by=c("periodo","cod"))

# Trimmed mean nossa implementacao
trimmed_mean_prop <- function(vars, pesos, lo=0.20, up=0.80) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  vars <- vars[ok]; pesos <- pesos[ok]
  if (!length(vars)) return(NA_real_)
  ord <- order(vars); vars <- vars[ord]; pesos <- pesos[ord]
  tp <- sum(pesos)
  ce <- cumsum(pesos) / tp
  cs <- ce - pesos / tp
  el <- pmax(cs, lo); eu <- pmin(ce, up)
  ov <- pmax(eu - el, 0)
  if (sum(ov) <= 0) return(NA_real_)
  sum(vars * ov) / sum(ov)
}

# Alternativa: binary include (exclui inteiro se center fora de [lo,up])
trimmed_mean_binary <- function(vars, pesos, lo=0.20, up=0.80) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  vars <- vars[ok]; pesos <- pesos[ok]
  if (!length(vars)) return(NA_real_)
  ord <- order(vars); vars <- vars[ord]; pesos <- pesos[ord]
  tp <- sum(pesos)
  ce <- cumsum(pesos) / tp
  cs <- ce - pesos / tp
  cm <- (cs + ce) / 2  # midpoint do bin de peso do item
  keep <- cm >= lo & cm <= up
  if (!any(keep)) return(NA_real_)
  sum(vars[keep] * pesos[keep]) / sum(pesos[keep])
}

# IPCA full (peso ponderado) — sanity check
ipca_full <- function(vars, pesos) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  sum(vars[ok] * pesos[ok]) / sum(pesos[ok])
}

cat("\n[3] Comparativo por mes:\n")
cat(sprintf("  %-8s %5s %8s %10s %10s %10s\n",
            "periodo", "n", "Σpeso", "IPCA_full", "MA_prop", "MA_bin"))
for (per in PERIODOS) {
  sub <- m[m$periodo == per, ]
  cat(sprintf("  %-8s %5d %8.4f %10.4f %10.4f %10.4f\n",
              per, nrow(sub), sum(sub$peso_mm, na.rm=TRUE),
              ipca_full(sub$var_mm, sub$peso_mm),
              trimmed_mean_prop(sub$var_mm, sub$peso_mm),
              trimmed_mean_binary(sub$var_mm, sub$peso_mm)))
}

# Detalhe: jan/2022 — top 20 itens por var (positivos) e bottom 20 (negativos)
cat("\n[4] JAN/2022 — top 15 itens POSITIVOS por var:\n")
sub <- m[m$periodo == "202201", ]
sub <- sub[order(-sub$var_mm), ]
sub$cum_peso <- cumsum(sub$peso_mm) / sum(sub$peso_mm)
print(head(sub[, c("cod","cat_nome","var_mm","peso_mm","cum_peso")], 15), row.names=FALSE)

cat("\n[5] JAN/2022 — top 15 itens NEGATIVOS por var:\n")
sub <- sub[order(sub$var_mm), ]
sub$cum_peso_rev <- cumsum(sub$peso_mm) / sum(sub$peso_mm)
print(head(sub[, c("cod","cat_nome","var_mm","peso_mm","cum_peso_rev")], 15), row.names=FALSE)

# Lista quais itens estao na faixa [20-80] do peso cumulativo
cat("\n[6] JAN/2022 — itens NO MEIO [20-80] do peso cumulativo (que entram no MA):\n")
sub <- m[m$periodo == "202201", ]
sub <- sub[order(sub$var_mm), ]
sub <- sub[!is.na(sub$var_mm) & !is.na(sub$peso_mm) & sub$peso_mm > 0, ]
sub$cum_peso <- cumsum(sub$peso_mm) / sum(sub$peso_mm)
sub$cum_start <- sub$cum_peso - sub$peso_mm/sum(sub$peso_mm)
mid <- sub[sub$cum_peso >= 0.20 & sub$cum_start <= 0.80, ]
mid$cont <- mid$var_mm * mid$peso_mm
cat(sprintf("   N=%d itens com peso total=%.4f, var media ponderada=%.4f\n",
            nrow(mid), sum(mid$peso_mm), sum(mid$cont)/sum(mid$peso_mm)))
print(head(mid[order(-mid$var_mm), c("cod","cat_nome","var_mm","peso_mm","cum_start","cum_peso")], 10), row.names=FALSE)
cat("   ...bottom 10:\n")
print(tail(mid[order(-mid$var_mm), c("cod","cat_nome","var_mm","peso_mm","cum_start","cum_peso")], 10), row.names=FALSE)
