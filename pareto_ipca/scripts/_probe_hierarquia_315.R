# Inspeciona quais niveis de codigo existem na classificacao 315 do T7060.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

url <- "https://servicodados.ibge.gov.br/api/v3/agregados/7060/periodos/202201/variaveis/63?localidades=N1[all]&classificacao=315[all]"
r <- GET(url, timeout(120))
raw <- fromJSON(content(r, "text", encoding="UTF-8"), simplifyDataFrame=FALSE)
rows <- list()
for (vn in raw) for (rn in vn$resultados) {
  cls <- rn$classificacoes[[1]]
  for (s in rn$series) {
    rows[[length(rows) + 1]] <- list(cat_nome = cls$categoria[[1]])
  }
}
nomes <- sapply(rows, `[[`, "cat_nome")
nomes <- unique(nomes)
cods  <- sub("^([0-9]+)\\..*$","\\1",nomes)
cods  <- ifelse(cods == nomes, NA_character_, cods)
ok    <- !is.na(cods)
cods  <- cods[ok]; nomes <- nomes[ok]

cat("[1] Distribuicao por nchar(cod):\n")
print(table(nchar(cods)))

for (nc in sort(unique(nchar(cods)))) {
  cat(sprintf("\n[2] Primeiros 6 codigos com nchar=%d:\n", nc))
  idx <- which(nchar(cods) == nc)
  for (i in head(idx, 6)) cat(sprintf("    %s | %s\n", cods[i], substr(nomes[i], 1, 70)))
}
