# Testa varias listas de itens suavizados pra MS, achar a que melhor bate BCB.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

PERIODOS <- c()
for (y in 2010:2024) for (m in 1:12) PERIODOS <- c(PERIODOS, sprintf("%d%02d", y, m))
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

cat("[1] Fetch V63 + V66 a nivel item...\n")
v63 <- fetch_long(63); names(v63)[3] <- "var_mm"
v66 <- fetch_long(66); names(v66)[3] <- "peso_mm"
itm <- merge(v63[, c("periodo","cod","cat_nome","var_mm")],
             v66[, c("periodo","cod","peso_mm")], by=c("periodo","cod"))

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

# Smoothing helper: aplica MM12m em itens da lista
smooth_items <- function(df_in, codes) {
  out <- df_in[order(df_in$cod, df_in$periodo), ]
  codes_av <- intersect(codes, unique(out$cod))
  for (cod in codes_av) {
    idx <- which(out$cod == cod)
    v <- out$var_mm[idx]
    v_s <- rep(NA_real_, length(v))
    for (i in seq_along(v)) {
      lo <- max(1L, i - 11L); w <- v[lo:i]; w <- w[!is.na(w)]
      if (length(w) >= 1L) v_s[i] <- mean(w)
    }
    out$var_mm[idx] <- v_s
  }
  list(df = out, n_codes = length(codes_av))
}

cat("[2] Fetch BCB MS (4466)...\n")
r <- GET("https://api.bcb.gov.br/dados/serie/bcdata.sgs.4466/dados?formato=json", timeout(60))
ms <- fromJSON(content(r,"text",encoding="UTF-8"), simplifyDataFrame=TRUE)
ms$periodo <- format(as.Date(ms$data,format="%d/%m/%Y"),"%Y%m")
ms_map <- setNames(as.numeric(ms$valor), ms$periodo)

eval_list <- function(label, codes) {
  res <- smooth_items(itm, codes)
  diffs <- numeric()
  for (per in PERIODOS) {
    if (is.na(ms_map[per])) next
    s <- res$df[res$df$periodo == per, ]
    if (!nrow(s)) next
    diffs <- c(diffs, trim(s$var_mm, s$peso_mm) - ms_map[per])
  }
  cat(sprintf("  %-22s (n_codes=%2d)  mean|d|=%.4f bias=%+.4f max|d|=%.4f\n",
              label, res$n_codes, mean(abs(diffs)), mean(diffs), max(abs(diffs))))
}

cat("\n[3] Lista MS atual (9 itens):\n")
L1 <- c("3101","3102","3201","3301","4501","5202","6201","7401","8101")
eval_list("L1: 9 itens base", L1)

cat("\n[4] +reparos (3103) + papelaria (8203):\n")
L2 <- c(L1, "3103","8203")
eval_list("L2: +reparos+pap", L2)

cat("\n[5] +produto farmaceutico (6101) + telecom (9101):\n")
L3 <- c(L1, "6101","9101")
eval_list("L3: +farm+tel", L3)

cat("\n[6] L1 + L2 + L3:\n")
L4 <- unique(c(L1, "3103","8203","6101","9101"))
eval_list("L4: union", L4)

cat("\n[7] L4 + servicos pessoais (4101 roupa, 4202 calcado, 7101 lazer, 7201 fumo):\n")
L5 <- unique(c(L4, "4101","4202","7101","7201"))
eval_list("L5: +diversos", L5)

cat("\n[8] Lista ULTRA ampla — todos os itens de servicos + habitacao + saude + educacao:\n")
# Pega prefixo: 3=habitacao, 4501/4502=empreg dom, 6201/6202=plano, 8101/8102/8103=educ, 7101/7102=lazer, 9101=telecom
L6 <- unique(c(itm$cod[substr(itm$cod,1,1) == "3"],  # toda habitacao
               "4501","4502","5202","6101","6201","6202","7101","7102","7401","7402",
               "8101","8102","8103","8201","8202","8203","9101","9102"))
eval_list("L6: ultra ampla", L6)

cat("\n[9] So administrados+contratos (sem livres):\n")
# Itens onde reajuste e' definido por contrato/regulacao (admin) ou mensalidade
L7 <- c("3101","3102","3201","3202","3301","3302","4501",
        "5101","5102","5202","6201","7301","7401","8101","8201","9101","9102")
eval_list("L7: admin+contratos", L7)

cat("\n[10] Apenas os itens com pico anual confirmado:\n")
L8 <- c("3102","5202","6201","8101")  # IPTU, IPVA, Plano saude, Mensalidades
eval_list("L8: so picos anuais", L8)
