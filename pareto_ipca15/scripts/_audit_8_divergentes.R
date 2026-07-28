#!/usr/bin/env Rscript
# _audit_8_divergentes.R — auditoria das 8 séries que o seed pula.
# Objetivo: descobrir se a divergência avg|diff| 0.14–1.65pp é:
#   (a) máscara errada (viés sistemático)
#   (b) BCB aplica processamento extra (ruído + viés baixo)
#   (c) universo de subitens divergente (BCB inclui/exclui itens)
#
# Testes:
#   T1: erro real (mean|diff|, bias, RMSE) nas séries que JÁ validamos
#       contra BCB no recon (comerc/ncomerc — temos 24 obs).
#   T2: BCB self-consistency — SGS_1635+1636+1637 deve = SGS_27864?
#       Se NÃO, prova que BCB usa universo diferente do nosso (subgrupo 11).
#   T3: comparar nossa recon (alim_in_natura/semi_elab/industr) com SGS
#       1635/1636/1637 diretos — mês a mês, bias vs ruído.
#   T4: idem para SGS 10841 (bens não-duráveis BCB) vs nosso ndur_industr.

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  setwd(dirname(dirname(normalizePath(sub("^--file=", "", .farg[1])))))
}
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

fetch_bcb <- function(code) {
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  r <- GET(url, timeout(120))
  if (status_code(r) != 200) stop(sprintf("SGS %d HTTP %d", code, status_code(r)))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"))
  data.frame(date = as.Date(raw$data, format = "%d/%m/%Y"),
             value = as.numeric(raw$valor), stringsAsFactors = FALSE)
}

cat("======================================================================\n")
cat("T1 — Erros reais (nossas validações no recon, 24 obs 2024-05 → 2026-04)\n")
cat("======================================================================\n")
val <- read.csv("scripts/outputs/ipca_validacao_bcb.csv", stringsAsFactors = FALSE)
cat(sprintf("Janela: %s a %s (%d obs)\n",
            min(val$periodo), max(val$periodo), nrow(val)))

summarize <- function(diffs, lbl) {
  d <- diffs[!is.na(diffs)]
  cat(sprintf("  %-25s mean|d|=%.4f bias=%+.4f RMSE=%.4f max|d|=%.4f\n",
              lbl, mean(abs(d)), mean(d), sqrt(mean(d^2)), max(abs(d))))
}
summarize(val$diff_admin,     "admin (controle ok)")
summarize(val$diff_livres,    "livres (controle ok)")
summarize(val$diff_industr,   "industriais (ctrl ok)")
summarize(val$diff_serv,      "servicos (ctrl ok)")
summarize(val$diff_alim_dom,  "alim_dom (ctrl ok)")
summarize(val$diff_comerc,    "comerc (suspeita)")
summarize(val$diff_ncomerc,   "ncomerc (suspeita)")

cat("\n======================================================================\n")
cat("T2 — BCB self-consistency: SGS_1635+1636+1637 deveria bater SGS_27864?\n")
cat("======================================================================\n")
cat("Baixando SGS 1635 (alim in-natura BCB)...\n");  s1635 <- fetch_bcb(1635)
cat("Baixando SGS 1636 (alim semi-elab BCB)...\n");  s1636 <- fetch_bcb(1636)
cat("Baixando SGS 1637 (alim industr BCB)...\n");    s1637 <- fetch_bcb(1637)
cat("Baixando SGS 27864 (alim domicilio total BCB)...\n"); s27864 <- fetch_bcb(27864)

# Pra somar variações mensais sem pesos é matematicamente errado, mas é o que dá
# pra fazer sem ter os pesos. Então o teste é: tem RELAÇÃO entre soma simples e
# o total? Se sim, podemos refinar. Se não, indica universo/método muito distinto.
names(s1635)[2] <- "v1635"; names(s1636)[2] <- "v1636"
names(s1637)[2] <- "v1637"; names(s27864)[2] <- "v27864"
m <- Reduce(function(a,b) merge(a,b,by="date",all=FALSE),
            list(s1635, s1636, s1637, s27864))
m$soma_simples <- m$v1635 + m$v1636 + m$v1637
m$mean_simples <- (m$v1635 + m$v1636 + m$v1637) / 3
m$diff_soma_vs_total <- m$soma_simples - m$v27864
m$diff_mean_vs_total <- m$mean_simples - m$v27864

cat(sprintf("\nOverlap BCB 1635/1636/1637/27864: %s → %s (%d obs)\n",
            format(min(m$date)), format(max(m$date)), nrow(m)))
cat("\nSe BCB usasse universo idêntico ao alim_dom, esperaríamos que a média\n")
cat("ponderada dos 3 = v27864. Sem os pesos, testamos a média simples como proxy:\n")
cat(sprintf("  mean|mean_simples - v27864| = %.4f pp\n",
            mean(abs(m$diff_mean_vs_total))))
cat(sprintf("  bias                         = %+.4f pp\n",
            mean(m$diff_mean_vs_total)))
cat(sprintf("  correlação(mean_simples, v27864) = %.4f\n",
            cor(m$mean_simples, m$v27864)))

# Teste mais robusto: regressão linear v27864 ~ v1635 + v1636 + v1637.
# Se os 3 cobrem o mesmo universo do total, os coefs (pesos implícitos) devem
# somar ~1 e o intercepto ~0.
fit <- lm(v27864 ~ v1635 + v1636 + v1637, data = m)
cat("\nRegressão v27864 ~ v1635 + v1636 + v1637 (coefs = pesos implícitos):\n")
co <- coef(fit)
cat(sprintf("  intercepto:    %+.4f (esperado ~0)\n", co[1]))
cat(sprintf("  beta_1635:     %+.4f\n", co[2]))
cat(sprintf("  beta_1636:     %+.4f\n", co[3]))
cat(sprintf("  beta_1637:     %+.4f\n", co[4]))
cat(sprintf("  soma_betas:    %+.4f (esperado ~1 se universos batem)\n", sum(co[2:4])))
cat(sprintf("  R²:            %.4f\n", summary(fit)$r.squared))
cat(sprintf("  resid SE:      %.4f pp\n", summary(fit)$sigma))

cat("\n======================================================================\n")
cat("T3 — Nossa recon (alim_in/se/ind) vs BCB SGS 1635/1636/1637 direto\n")
cat("======================================================================\n")
recon <- read.csv("scripts/outputs/ipca_reconstruido.csv", stringsAsFactors = FALSE)
recon$date <- as.Date(paste0(substr(recon$periodo,1,4),"-",
                              substr(recon$periodo,5,6),"-01"))

cmp <- merge(recon[, c("date","var_alim_in","var_alim_se","var_alim_ind")],
             merge(merge(s1635, s1636, by="date"), s1637, by="date"),
             by="date")
cmp$d_in  <- cmp$var_alim_in  - cmp$v1635
cmp$d_se  <- cmp$var_alim_se  - cmp$v1636
cmp$d_ind <- cmp$var_alim_ind - cmp$v1637

cat(sprintf("\nOverlap: %s → %s (%d obs)\n",
            format(min(cmp$date)), format(max(cmp$date)), nrow(cmp)))
summarize(cmp$d_in,  "alim_in_natura  (recon-BCB)")
summarize(cmp$d_se,  "alim_semi_elab  (recon-BCB)")
summarize(cmp$d_ind, "alim_industr    (recon-BCB)")

cat("\nDirecionalidade: se bias é grande e consistente → universo divergente.\n")
cat("                 se bias ~0 mas mean|d| alto → ruído (BCB suaviza/repondera).\n")

cat("\n======================================================================\n")
cat("T4 — SGS 10841 (bens não-dur BCB) vs nosso ndur_industr+alim_in+alim_se\n")
cat("======================================================================\n")
# Comentário do recon (linha 421-422): SGS 10841 = ndur_industr + alim_in_natura + alim_semi_elab
cat("Baixando SGS 10841 (bens não-duráveis BCB)...\n"); s10841 <- fetch_bcb(10841)
names(s10841)[2] <- "bcb_ndur"

cmp2 <- merge(recon[, c("date","var_ndind","var_alim_in","var_alim_se",
                         "peso_ndind","peso_alim_in","peso_alim_se")],
              s10841, by="date")
cmp2$var_ndur_recomp <- (cmp2$var_ndind   * cmp2$peso_ndind +
                         cmp2$var_alim_in * cmp2$peso_alim_in +
                         cmp2$var_alim_se * cmp2$peso_alim_se) /
                        (cmp2$peso_ndind + cmp2$peso_alim_in + cmp2$peso_alim_se)
cmp2$d <- cmp2$var_ndur_recomp - cmp2$bcb_ndur

cat(sprintf("\nOverlap: %s → %s (%d obs)\n",
            format(min(cmp2$date)), format(max(cmp2$date)), nrow(cmp2)))
summarize(cmp2$d, "ndur_recomp - SGS 10841")

cat("\n======================================================================\n")
cat("CONCLUSÃO — leia os números acima:\n")
cat("======================================================================\n")
cat("- T1 isola se a divergência aparece nas 24 obs que JÁ temos validadas.\n")
cat("- T2 prova/refuta se BCB usa universo idêntico ao alim_dom (subgrupo 11).\n")
cat("- T3 quantifica bias vs ruído pras 3 séries de alimentos.\n")
cat("- T4 idem para a recomposição dos não-duráveis (10841).\n")
cat("Interpretação: bias |x| > 3*ruído → universo/método divergente (causa #1/#3)\n")
cat("               bias ≈ 0 mas RMSE alto → BCB suaviza/repondera     (causa #2)\n")
