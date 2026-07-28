# Calibra: qual trim level reproduz BCB MA nos meses-problema?
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c("202112","202201","202202","202203","202204","202205","202206","202207","202208","202209")
BCB_MA <- c("202112"=0.67,"202201"=0.68,"202202"=0.72,"202203"=1.45,"202204"=1.13,
            "202205"=0.89,"202206"=0.71,"202207"=-0.07,"202208"=0.05,"202209"=0.45)

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
  d[!is.na(d$cod) & nchar(d$cod) == 7, ]
}

cat("[1] Fetch V63 + V66...\n")
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
agg <- function(vars,pesos){ ok<-!is.na(vars)&!is.na(pesos)&pesos>0; sum(vars[ok]*pesos[ok])/sum(pesos[ok]) }

# Grid de trims (simetricos por enquanto)
trims <- list(c(0.20,0.80), c(0.15,0.85), c(0.10,0.90), c(0.05,0.95),
              c(0.25,0.75), c(0.30,0.70))
labs  <- c("20/80","15/85","10/90","05/95","25/75","30/70")

cat(sprintf("\n%-8s %8s %8s", "periodo", "BCB_MA", "IPCAfull"))
for (l in labs) cat(sprintf(" %8s", l))
cat("\n")
for (per in PERIODOS) {
  s <- m[m$periodo == per, ]
  cat(sprintf("%-8s %+8.3f %+8.3f", per, BCB_MA[per], agg(s$var_mm, s$peso_mm)))
  for (i in seq_along(trims)) {
    v <- trim(s$var_mm, s$peso_mm, trims[[i]][1], trims[[i]][2])
    cat(sprintf(" %+8.3f", v))
  }
  cat("\n")
}

# Tambem testa: trim assimetrico (diferentes alphas no lower/upper)
cat("\n[2] Assimetrico (alpha_L menor que alpha_U):\n")
trims2 <- list(c(0.10,0.80), c(0.15,0.80), c(0.05,0.80),
               c(0.10,0.85), c(0.05,0.90), c(0.00,0.85))
labs2 <- c("10/80","15/80","5/80","10/85","5/90","0/85")
cat(sprintf("%-8s %8s", "periodo","BCB_MA"))
for (l in labs2) cat(sprintf(" %8s", l)); cat("\n")
for (per in PERIODOS) {
  s <- m[m$periodo == per, ]
  cat(sprintf("%-8s %+8.3f", per, BCB_MA[per]))
  for (i in seq_along(trims2)) {
    v <- trim(s$var_mm, s$peso_mm, trims2[[i]][1], trims2[[i]][2])
    cat(sprintf(" %+8.3f", v))
  }
  cat("\n")
}
