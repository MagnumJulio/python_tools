# Testa hipotese EE102: MA usa nivel ITEM (5 digitos), nao subitem (7 digitos).
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c("202112","202201","202202","202203","202204","202205",
              "202206","202207","202208","202209","202210","202211","202212",
              "202301","202302","202303","202304","202305")
BCB_MA <- c("202112"=0.67,"202201"=0.68,"202202"=0.72,"202203"=1.45,"202204"=1.13,
            "202205"=0.89,"202206"=0.71,"202207"=-0.07,"202208"=0.05,"202209"=0.45,
            "202210"=0.41,"202211"=0.35,"202212"=0.49,
            "202301"=0.56,"202302"=0.62,"202303"=0.38,"202304"=0.45,"202305"=0.46)

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
  d
}

cat("[1] Fetch V63 (var) + V66 (peso) — todas hierarquias...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"

# Filtra: subitens (7 dig) e itens (5 dig)
subi63 <- v63[!is.na(v63$cod) & nchar(v63$cod) == 7, ]
subi66 <- v66[!is.na(v66$cod) & nchar(v66$cod) == 7, ]
item63 <- v63[!is.na(v63$cod) & nchar(v63$cod) == 4, ]
item66 <- v66[!is.na(v66$cod) & nchar(v66$cod) == 4, ]

cat(sprintf("    Universo: %d subitens, %d itens\n",
            length(unique(subi63$cod)), length(unique(item63$cod))))

# SUBITEM merge
subi <- merge(subi63[,c("periodo","cod","var_mm")], subi66[,c("periodo","cod","peso_mm")],
              by=c("periodo","cod"))
# ITEM merge (direto do SIDRA, nao agregado por nos)
item <- merge(item63[,c("periodo","cod","var_mm")], item66[,c("periodo","cod","peso_mm")],
              by=c("periodo","cod"))

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
agg <- function(vars,pesos){ ok<-!is.na(vars)&!is.na(pesos)&pesos>0; sum(vars[ok]*pesos[ok])/sum(pesos[ok]) }

cat("\n[2] Comparativo MA(20/80) usando SUBITEM (377) vs ITEM (53):\n")
cat(sprintf("  %-8s %8s %10s %10s %10s %10s %10s\n",
            "periodo","BCB_MA","IPCA_subi","MA_subi","IPCA_item","MA_item","diff_MA"))
for (per in PERIODOS) {
  s <- subi[subi$periodo == per, ]
  it <- item[item$periodo == per, ]
  ma_s <- trim(s$var_mm, s$peso_mm)
  ma_i <- trim(it$var_mm, it$peso_mm)
  cat(sprintf("  %-8s %+8.3f %10.4f %10.4f %10.4f %10.4f %+10.4f\n",
              per, BCB_MA[per],
              agg(s$var_mm, s$peso_mm), ma_s,
              agg(it$var_mm, it$peso_mm), ma_i,
              ma_i - BCB_MA[per]))
}

# Stats globais (resumo)
cat("\n[3] Stats sumario (ours - BCB) nos meses do teste:\n")
diffs_subi <- numeric()
diffs_item <- numeric()
for (per in PERIODOS) {
  s <- subi[subi$periodo == per, ]
  it <- item[item$periodo == per, ]
  diffs_subi <- c(diffs_subi, trim(s$var_mm, s$peso_mm) - BCB_MA[per])
  diffs_item <- c(diffs_item, trim(it$var_mm, it$peso_mm) - BCB_MA[per])
}
cat(sprintf("  MA_subi: bias=%+.4f mean|d|=%.4f max|d|=%.4f\n",
            mean(diffs_subi), mean(abs(diffs_subi)), max(abs(diffs_subi))))
cat(sprintf("  MA_item: bias=%+.4f mean|d|=%.4f max|d|=%.4f\n",
            mean(diffs_item), mean(abs(diffs_item)), max(abs(diffs_item))))
