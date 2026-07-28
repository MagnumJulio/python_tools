#!/usr/bin/env Rscript
# Compara cobertura da máscara extended vs base
m1 <- read.csv("scripts/ipca_masks/classificacao.csv", stringsAsFactors = FALSE)
m2 <- read.csv("scripts/ipca_masks/classificacao_extended.csv", stringsAsFactors = FALSE)
m1$cod_ibge <- as.character(m1$cod_ibge); m2$cod_ibge <- as.character(m2$cod_ibge)
cat(sprintf("base:     %d subitens\nextended: %d subitens\n", nrow(m1), nrow(m2)))
cat(sprintf("códigos só em extended: %d\n", length(setdiff(m2$cod_ibge, m1$cod_ibge))))
extras <- setdiff(m2$cod_ibge, m1$cod_ibge)
cat("amostra dos extras:\n")
ex <- m2[m2$cod_ibge %in% head(extras, 20), c("cod_ibge","nome","classe")]
print(ex, row.names = FALSE)
