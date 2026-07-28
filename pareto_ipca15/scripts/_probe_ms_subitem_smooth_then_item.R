# Hipotese: BCB suaviza SUBITENS (com lista cirurgica) -> re-agrega pra item -> trim 20/80
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c()
for (y in 2014:2024) for (m in 1:12) PERIODOS <- c(PERIODOS, sprintf("%d%02d", y, m))

SIDRA_AGG <- 7060L; SIDRA_CLS <- 315L

# Lista oficial de SUBITENS suavizados (7 digitos)
MS_SUAVIZADOS_SI <- c(
  "3101001","3101002",                  # Aluguel + Condominio
  "3201001","3201002",                  # Agua/esgoto
  "3301001","3301002",                  # Energia + gas
  "4501007","4501009",                  # Empregada + diarista
  "6201002","6201013","6201018",        # Plano saude
  "8101001","8101002","8101003","8101004","8101005",
  "8101006","8101007","8101008","8101009","8101010",
  "8101011","8101012","8101013",        # Mensalidades
  "7401001","7401002",                  # Jogos
  "3102001",                            # IPTU
  "5202005"                             # IPVA
)

url_str <- function(var, perds) {
  sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]&classificacao=%d[all]",
          SIDRA_AGG, paste(perds, collapse=","), var, SIDRA_CLS)
}
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

cat("[1] Fetch V63 + V66 (todos niveis)...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"

# subitens (7 dig)
subi <- merge(v63[!is.na(v63$cod) & nchar(v63$cod)==7, c("periodo","cod","var_mm")],
              v66[!is.na(v66$cod) & nchar(v66$cod)==7, c("periodo","cod","peso_mm")],
              by=c("periodo","cod"))
# itens (4 dig) - direto do SIDRA
item_sidra <- merge(v63[!is.na(v63$cod) & nchar(v63$cod)==4, c("periodo","cod","var_mm")],
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

# === STRAT A: suaviza SUBITENS da lista, re-agrega pra item, trim ===
subi_ms <- subi[order(subi$cod, subi$periodo), ]
codes_si <- intersect(MS_SUAVIZADOS_SI, unique(subi_ms$cod))
cat(sprintf("    Lista SI: %d / %d subitens disponiveis\n", length(codes_si), length(MS_SUAVIZADOS_SI)))

for (cod in codes_si) {
  idx <- which(subi_ms$cod == cod)
  v <- subi_ms$var_mm[idx]
  v_smooth <- rep(NA_real_, length(v))
  for (i in seq_along(v)) {
    lo <- max(1L, i - 11L)
    w <- v[lo:i]; w <- w[!is.na(w)]
    if (length(w) >= 1L) v_smooth[i] <- mean(w)
  }
  subi_ms$var_mm[idx] <- v_smooth
}

# Re-agrega pra item: substr(cod, 1, 4)
subi_ms$item_cod <- substr(subi_ms$cod, 1, 4)
item_agg <- aggregate(cbind(prod = subi_ms$var_mm * subi_ms$peso_mm,
                            w = subi_ms$peso_mm),
                      by = list(periodo = subi_ms$periodo, cod = subi_ms$item_cod),
                      FUN = sum, na.rm = TRUE)
item_agg$var_mm <- item_agg$prod / item_agg$w
item_agg$peso_mm <- item_agg$w

# === STRAT B: itens diretos do SIDRA (sem suavizar nada) — controle MA ===
# === STRAT C: smooth ITEM-level (o que faziamos antes da revisao) ===
MS_SUAVIZADOS_ITEM <- c("3101","3102","3201","3301","4501","5202","6201","7401","8101")
item_smooth_lvl <- item_sidra[order(item_sidra$cod, item_sidra$periodo), ]
for (cod in MS_SUAVIZADOS_ITEM) {
  idx <- which(item_smooth_lvl$cod == cod)
  if (!length(idx)) next
  v <- item_smooth_lvl$var_mm[idx]
  v_smooth <- rep(NA_real_, length(v))
  for (i in seq_along(v)) {
    lo <- max(1L, i - 11L)
    w <- v[lo:i]; w <- w[!is.na(w)]
    if (length(w) >= 1L) v_smooth[i] <- mean(w)
  }
  item_smooth_lvl$var_mm[idx] <- v_smooth
}

cat("[2] Fetch BCB SGS 11426 (MA) + 4466 (MS)...\n")
fetch_sgs <- function(c) {
  r <- GET(sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", c), timeout(60))
  d <- fromJSON(content(r,"text",encoding="UTF-8"), simplifyDataFrame=TRUE)
  d$periodo <- format(as.Date(d$data,format="%d/%m/%Y"),"%Y%m")
  d$valor <- as.numeric(d$valor)
  setNames(d$valor, d$periodo)
}
ma_map <- fetch_sgs(11426)
ms_map <- fetch_sgs(4466)

cat("\n[3] Compute MA + MS strats por mes:\n")
d_ma <- d_msA <- d_msC <- numeric()
for (per in PERIODOS) {
  if (is.na(ms_map[per])) next
  is_per  <- item_sidra[item_sidra$periodo == per, ]
  ia_per  <- item_agg[item_agg$periodo == per, ]
  isl_per <- item_smooth_lvl[item_smooth_lvl$periodo == per, ]
  if (!nrow(is_per) || !nrow(ia_per)) next
  v_ma  <- trim(is_per$var_mm, is_per$peso_mm)
  v_msA <- trim(ia_per$var_mm, ia_per$peso_mm)
  v_msC <- trim(isl_per$var_mm, isl_per$peso_mm)
  d_ma  <- c(d_ma,  v_ma  - ma_map[per])
  d_msA <- c(d_msA, v_msA - ms_map[per])
  d_msC <- c(d_msC, v_msC - ms_map[per])
}

cat(sprintf("\n  [MA item]            mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
            mean(abs(d_ma)), mean(d_ma), max(abs(d_ma))))
cat(sprintf("  [MS-A smooth subi->item->trim]  mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
            mean(abs(d_msA)), mean(d_msA), max(abs(d_msA))))
cat(sprintf("  [MS-C smooth item-level]        mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
            mean(abs(d_msC)), mean(d_msC), max(abs(d_msC))))

# STRAT D: smooth-subitem + trim 20/80 a NIVEL SUBITEM (estado original)
cat("\n[D] Smooth-subitem + trim-subitem (estado previo):\n")
subi_ms_full <- subi[order(subi$cod, subi$periodo), ]
for (cod in codes_si) {
  idx <- which(subi_ms_full$cod == cod)
  v <- subi_ms_full$var_mm[idx]
  v_smooth <- rep(NA_real_, length(v))
  for (i in seq_along(v)) {
    lo <- max(1L, i - 11L); w <- v[lo:i]; w <- w[!is.na(w)]
    if (length(w) >= 1L) v_smooth[i] <- mean(w)
  }
  subi_ms_full$var_mm[idx] <- v_smooth
}
d_msD <- d_maSI <- numeric()
for (per in PERIODOS) {
  if (is.na(ms_map[per])) next
  sd_per <- subi_ms_full[subi_ms_full$periodo == per, ]
  s_per <- subi[subi$periodo == per, ]
  if (!nrow(sd_per)) next
  d_msD <- c(d_msD, trim(sd_per$var_mm, sd_per$peso_mm) - ms_map[per])
  d_maSI <- c(d_maSI, trim(s_per$var_mm, s_per$peso_mm) - ma_map[per])
}
cat(sprintf("  [MA subi] mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
            mean(abs(d_maSI)), mean(d_maSI), max(abs(d_maSI))))
cat(sprintf("  [MS-D smooth subi + trim subi] mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
            mean(abs(d_msD)), mean(d_msD), max(abs(d_msD))))
