# Bateria de variantes pra MS e DP, procurando casar com BCB.
# Janela: 2014-2024 (10 anos, robusto sem T2938).
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c()
for (y in 2014:2024) for (m in 1:12) PERIODOS <- c(PERIODOS, sprintf("%d%02d", y, m))
SIDRA_AGG <- 7060L; SIDRA_CLS <- 315L

MS_SUAVIZADOS <- c(
  "3101001","3101002","3201001","3201002","3301001","3301002",
  "4501007","4501009","6201002","6201013","6201018",
  "8101001","8101002","8101003","8101004","8101005","8101006","8101007",
  "8101008","8101009","8101010","8101011","8101012","8101013",
  "7401001","7401002","3102001","5202005"
)

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
  d
}

cat("[1] Fetch SIDRA V63 + V66 (subitens + itens)...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"
subi <- merge(v63[!is.na(v63$cod) & nchar(v63$cod)==7, c("periodo","cod","var_mm")],
              v66[!is.na(v66$cod) & nchar(v66$cod)==7, c("periodo","cod","peso_mm")],
              by=c("periodo","cod"))
itm <- merge(v63[!is.na(v63$cod) & nchar(v63$cod)==4, c("periodo","cod","var_mm")],
             v66[!is.na(v66$cod) & nchar(v66$cod)==4, c("periodo","cod","peso_mm")],
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

cat("[2] Fetch BCB MS (4466) + DP (16122)...\n")
fetch_sgs <- function(c) {
  r <- GET(sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", c), timeout(60))
  d <- fromJSON(content(r,"text",encoding="UTF-8"), simplifyDataFrame=TRUE)
  d$periodo <- format(as.Date(d$data,format="%d/%m/%Y"),"%Y%m")
  setNames(as.numeric(d$valor), d$periodo)
}
ms_map <- fetch_sgs(4466)
dp_map <- fetch_sgs(16122)

# ============================================================
# MS VARIANTES: smooth subitens lista, reagrega, trim
# ============================================================
smooth_subi <- function(df_in, codes, window_lo, window_hi) {
  # window_lo: meses pra tras (negativo), window_hi: meses pra frente
  # ex: trailing 12m = lo=-11, hi=0; centrado 12m = lo=-5, hi=6
  out <- df_in[order(df_in$cod, df_in$periodo), ]
  codes_av <- intersect(codes, unique(out$cod))
  for (cod in codes_av) {
    idx <- which(out$cod == cod)
    v <- out$var_mm[idx]
    n <- length(v)
    v_s <- rep(NA_real_, n)
    for (i in seq_len(n)) {
      lo <- max(1L, i + window_lo)
      hi <- min(n,  i + window_hi)
      w <- v[lo:hi]; w <- w[!is.na(w)]
      if (length(w) >= 1L) v_s[i] <- mean(w)
    }
    out$var_mm[idx] <- v_s
  }
  out
}

reagg_item <- function(subi_in) {
  subi_in$item_cod <- substr(subi_in$cod, 1, 4)
  agg <- aggregate(cbind(prod = subi_in$var_mm * subi_in$peso_mm, w = subi_in$peso_mm),
                   by = list(periodo = subi_in$periodo, cod = subi_in$item_cod),
                   FUN = sum, na.rm = TRUE)
  agg$var_mm <- agg$prod / agg$w
  agg$peso_mm <- agg$w
  agg
}

eval_ms <- function(label, smooth_df) {
  ig <- reagg_item(smooth_df)
  diffs <- numeric()
  for (per in PERIODOS) {
    if (is.na(ms_map[per])) next
    s <- ig[ig$periodo == per, ]
    if (!nrow(s)) next
    diffs <- c(diffs, trim(s$var_mm, s$peso_mm) - ms_map[per])
  }
  cat(sprintf("  %-30s  mean|d|=%.4f bias=%+.4f RMSE=%.4f max|d|=%.4f\n",
              label, mean(abs(diffs)), mean(diffs), sqrt(mean(diffs^2)), max(abs(diffs))))
}

cat("\n[3] === MS variantes ===\n")
eval_ms("trail 12m  (-11..0)",    smooth_subi(subi, MS_SUAVIZADOS, -11, 0))
eval_ms("trail 6m   (-5..0)",     smooth_subi(subi, MS_SUAVIZADOS, -5, 0))
eval_ms("trail 24m  (-23..0)",    smooth_subi(subi, MS_SUAVIZADOS, -23, 0))
eval_ms("centr 12m  (-5..+6)",    smooth_subi(subi, MS_SUAVIZADOS, -5, 6))
eval_ms("centr 13m  (-6..+6)",    smooth_subi(subi, MS_SUAVIZADOS, -6, 6))
eval_ms("centr 24m  (-11..+12)",  smooth_subi(subi, MS_SUAVIZADOS, -11, 12))
eval_ms("centr 6m   (-2..+3)",    smooth_subi(subi, MS_SUAVIZADOS, -2, 3))

# Variante: suavizacao via mediana (descarta outliers extremos)
smooth_median <- function(df_in, codes, w_lo, w_hi) {
  out <- df_in[order(df_in$cod, df_in$periodo), ]
  codes_av <- intersect(codes, unique(out$cod))
  for (cod in codes_av) {
    idx <- which(out$cod == cod)
    v <- out$var_mm[idx]; n <- length(v); v_s <- rep(NA_real_, n)
    for (i in seq_len(n)) {
      lo <- max(1L, i + w_lo); hi <- min(n, i + w_hi)
      w <- v[lo:hi]; w <- w[!is.na(w)]
      if (length(w) >= 1L) v_s[i] <- median(w)
    }
    out$var_mm[idx] <- v_s
  }
  out
}
eval_ms("median trail 12m",    smooth_median(subi, MS_SUAVIZADOS, -11, 0))
eval_ms("median centr 12m",    smooth_median(subi, MS_SUAVIZADOS, -5, 6))

# ============================================================
# DP VARIANTES
# ============================================================
weighted_mean_simple <- function(vars, pesos) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  if (!any(ok)) return(NA_real_)
  sum(vars[ok] * pesos[ok]) / sum(pesos[ok])
}

eval_dp <- function(label, itm_aug) {
  diffs <- numeric()
  for (per in PERIODOS) {
    if (is.na(dp_map[per])) next
    s <- itm_aug[itm_aug$periodo == per, ]
    s <- s[!is.na(s$sigma) & s$sigma > 1e-6, ]
    if (!nrow(s)) next
    wt <- s$peso_mm / s$sigma
    v <- weighted_mean_simple(s$var_mm, wt)
    diffs <- c(diffs, v - dp_map[per])
  }
  cat(sprintf("  %-35s  mean|d|=%.4f bias=%+.4f RMSE=%.4f max|d|=%.4f\n",
              label, mean(abs(diffs)), mean(diffs), sqrt(mean(diffs^2)), max(abs(diffs))))
}

cat("\n[4] === DP variantes ===\n")

# DP-1: sigma global
itm$periodo <- as.character(itm$periodo)
itm <- itm[order(itm$cod, itm$periodo), ]
sigma_g <- aggregate(var_mm ~ cod, data = itm,
                     FUN = function(v) { v <- v[!is.na(v)]; if (length(v)<6) NA_real_ else sd(v) })
names(sigma_g)[2] <- "sigma"
itm_dp1 <- merge(itm, sigma_g, by="cod", all.x=TRUE)
eval_dp("sigma global (uniforme)", itm_dp1)

# DP-2: sigma rolling 60m com expansivo (min 6)
sigma_rolling <- function(itm_in, win, min_obs) {
  out <- itm_in
  out$sigma <- NA_real_
  cods <- unique(out$cod)
  for (cd in cods) {
    idx <- which(out$cod == cd)
    o <- order(out$periodo[idx]); idx <- idx[o]
    v <- out$var_mm[idx]; n <- length(v)
    for (i in seq_len(n)) {
      lo <- max(1L, i - win + 1L)
      w <- v[lo:i]; w <- w[!is.na(w)]
      if (length(w) >= min_obs) out$sigma[idx[i]] <- sd(w)
    }
  }
  out
}
eval_dp("sigma rolling 60m (min 6)",    sigma_rolling(itm, 60, 6))
eval_dp("sigma rolling 60m (min 60)",   sigma_rolling(itm, 60, 60))
eval_dp("sigma rolling 36m (min 6)",    sigma_rolling(itm, 36, 6))
eval_dp("sigma rolling 24m (min 6)",    sigma_rolling(itm, 24, 6))
eval_dp("sigma rolling 120m (min 6)",   sigma_rolling(itm, 120, 6))

# DP-3: sigma rolling 60m CENTRADO
sigma_rolling_centr <- function(itm_in, win, min_obs) {
  out <- itm_in; out$sigma <- NA_real_
  half <- win %/% 2L
  cods <- unique(out$cod)
  for (cd in cods) {
    idx <- which(out$cod == cd); o <- order(out$periodo[idx]); idx <- idx[o]
    v <- out$var_mm[idx]; n <- length(v)
    for (i in seq_len(n)) {
      lo <- max(1L, i - half); hi <- min(n, i + half)
      w <- v[lo:hi]; w <- w[!is.na(w)]
      if (length(w) >= min_obs) out$sigma[idx[i]] <- sd(w)
    }
  }
  out
}
eval_dp("sigma rolling 60m CENTRADO",   sigma_rolling_centr(itm, 60, 6))
eval_dp("sigma rolling 24m CENTRADO",   sigma_rolling_centr(itm, 24, 6))

# DP usando 1ª diferença
itm_diff <- itm[order(itm$cod, itm$periodo), ]
itm_diff$diff1 <- NA_real_
for (cd in unique(itm_diff$cod)) {
  i <- which(itm_diff$cod == cd)
  v <- itm_diff$var_mm[i]
  itm_diff$diff1[i] <- c(NA, diff(v))
}
sigma_d <- aggregate(diff1 ~ cod, data = itm_diff,
                     FUN = function(v) { v <- v[!is.na(v)]; if (length(v)<6) NA_real_ else sd(v) })
names(sigma_d)[2] <- "sigma"
itm_dp_d <- merge(itm, sigma_d, by="cod", all.x=TRUE)
eval_dp("sigma da 1a diferenca (global)", itm_dp_d)
