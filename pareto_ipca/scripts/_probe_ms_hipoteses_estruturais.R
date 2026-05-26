# Testes ESTRUTURAIS pro MS: hipoteses que mudam o algoritmo, nao so o smoothing.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c()
for (y in 2020:2024) for (m in 1:12) PERIODOS <- c(PERIODOS, sprintf("%d%02d", y, m))
SIDRA_AGG <- 7060L; SIDRA_CLS <- 315L

url_str <- function(var, perds) sprintf(
  "https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=%d[all]",
  SIDRA_AGG, paste(perds, collapse=","), var, SIDRA_CLS)
fetch_long <- function(var) {
  r <- GET(url_str(var, PERIODOS), timeout(240))
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

cat("[1] Fetch item-level...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"
itm <- merge(v63[, c("periodo","cod","var_mm")], v66[, c("periodo","cod","peso_mm")], by=c("periodo","cod"))
itm <- itm[order(itm$cod, itm$periodo), ]

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

cat("[2] Fetch BCB MA + MS...\n")
fetch_sgs <- function(c) {
  r <- GET(sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", c), timeout(60))
  d <- fromJSON(content(r,"text",encoding="UTF-8"), simplifyDataFrame=TRUE)
  d$periodo <- format(as.Date(d$data,format="%d/%m/%Y"),"%Y%m")
  setNames(as.numeric(d$valor), d$periodo)
}
ma_map <- fetch_sgs(11426)
ms_map <- fetch_sgs(4466)

periodos_ord <- sort(unique(itm$periodo))

# === H1: Suavizar TODOS os itens (item-level) trailing 12m, depois trim ===
itm_all <- itm
cods_all <- unique(itm_all$cod)
for (cd in cods_all) {
  i <- which(itm_all$cod == cd); o <- order(itm_all$periodo[i]); i <- i[o]
  v <- itm_all$var_mm[i]; n <- length(v); v_s <- rep(NA_real_, n)
  for (k in seq_len(n)) {
    lo <- max(1L, k-11L); w <- v[lo:k]; w <- w[!is.na(w)]
    if (length(w)>=1L) v_s[k] <- mean(w)
  }
  itm_all$var_mm[i] <- v_s
}

# === H2: MS = MM12m da MA propria ===
ma_ours <- sapply(periodos_ord, function(p) {
  x <- itm[itm$periodo == p, ]; trim(x$var_mm, x$peso_mm)
})
names(ma_ours) <- periodos_ord
ms_h2_ours <- rep(NA_real_, length(ma_ours))
for (k in seq_along(ma_ours)) {
  lo <- max(1L, k-11L); w <- ma_ours[lo:k]; w <- w[!is.na(w)]
  if (length(w)>=1L) ms_h2_ours[k] <- mean(w)
}

# === H3: trim no item, depois aplica suavizacao a posteriori SO NOS ITENS LISTADOS antes do trim ===
# Diferente de H1: H1 suaviza todos, H3 nao suaviza ninguem mas vamos comparar.

# === H4: MM12m centrada da MA ===
ms_h4_ours <- rep(NA_real_, length(ma_ours))
for (k in seq_along(ma_ours)) {
  lo <- max(1L, k-5L); hi <- min(length(ma_ours), k+6L)
  w <- ma_ours[lo:hi]; w <- w[!is.na(w)]
  if (length(w)>=1L) ms_h4_ours[k] <- mean(w)
}

cat("\n[3] Resultados:\n")
print_eval <- function(label, vals) {
  d <- numeric()
  for (k in seq_along(periodos_ord)) {
    p <- periodos_ord[k]
    if (is.na(ms_map[p]) || is.na(vals[k])) next
    d <- c(d, vals[k] - ms_map[p])
  }
  cat(sprintf("  %-35s  n=%d  mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
              label, length(d), mean(abs(d)), mean(d), max(abs(d))))
}

# H1
ms_h1 <- sapply(periodos_ord, function(p) {
  x <- itm_all[itm_all$periodo == p, ]; trim(x$var_mm, x$peso_mm)
})
print_eval("H1: smooth ALL items trail12m -> trim", ms_h1)
print_eval("H2: MS = MM12m trailing da MA",        ms_h2_ours)
print_eval("H4: MS = MM12m centrada da MA",        ms_h4_ours)

# === H5: MS = MA + alfa * (MA_acumulada_12m_anualizada) — peso de tendencia ===
# tirado da ideia: BCB SDS de MS tem media maior que MA por capturar tendencia
ma_12m <- rep(NA_real_, length(ma_ours))
for (k in seq_along(ma_ours)) {
  lo <- max(1L, k-11L); w <- ma_ours[lo:k]; w <- w[!is.na(w)]
  if (length(w)>=1L) ma_12m[k] <- mean(w)
}
# H5a: 50-50 mix
ms_h5 <- 0.5*ma_ours + 0.5*ma_12m
print_eval("H5: MS = 0.5*MA + 0.5*MA_MM12m", ms_h5)

# === H6: comparativo com MA propria pra controle ===
print_eval("CONTROL: MA puro (deveria ser ~0 vs MA, nao MS)", ma_ours)

# === H7: olhar a relacao real entre MA e MS BCB ===
cat("\n[4] BCB: MS = f(MA)? Regressao\n")
ma_v <- ma_map[periodos_ord]; ms_v <- ms_map[periodos_ord]
keep <- !is.na(ma_v) & !is.na(ms_v)
cat(sprintf("  MS = %+.3f + %.3f*MA + e   (n=%d)\n",
            coef(lm(ms_v[keep] ~ ma_v[keep]))[1],
            coef(lm(ms_v[keep] ~ ma_v[keep]))[2],
            sum(keep)))
# Tendencia: regressao de MS BCB sobre MA + MM12m_MA
ma_mm12_bcb <- rep(NA_real_, length(ma_v))
for (k in seq_along(ma_v)) {
  lo <- max(1L, k-11L); w <- ma_v[lo:k]; w <- w[!is.na(w)]
  if (length(w)>=1L) ma_mm12_bcb[k] <- mean(w)
}
keep2 <- !is.na(ma_v) & !is.na(ms_v) & !is.na(ma_mm12_bcb)
mod <- lm(ms_v[keep2] ~ ma_v[keep2] + ma_mm12_bcb[keep2])
cat(sprintf("  MS = %+.3f + %.3f*MA + %.3f*MA_MM12m  (R2=%.3f)\n",
            coef(mod)[1], coef(mod)[2], coef(mod)[3], summary(mod)$r.squared))
