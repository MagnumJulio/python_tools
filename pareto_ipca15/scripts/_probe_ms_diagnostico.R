# Por que MS regrediu? Compara MS_BCB vs MA_BCB direto — quanto MS diverge de MA no BCB?
# Se a diferença for pequena, lista de suavização tem efeito marginal; problema é elsewhere.
# Se MS_BCB-MA_BCB tiver pattern claro, vemos onde a suavização atua mais.
suppressPackageStartupMessages({ library(httr); library(jsonlite) })

fetch_sgs <- function(code) {
  r <- GET(sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code), timeout(60))
  d <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = TRUE)
  d$periodo <- format(as.Date(d$data, format = "%d/%m/%Y"), "%Y%m")
  d$valor <- as.numeric(d$valor)
  d[, c("periodo", "valor")]
}

cat("[1] Fetch BCB MA (11426) + MS (4466)...\n")
ma <- fetch_sgs(11426); names(ma)[2] <- "ma"
ms <- fetch_sgs(4466);  names(ms)[2] <- "ms"
m <- merge(ma, ms, by="periodo")
m$diff <- m$ms - m$ma
m <- m[order(m$periodo), ]
m <- m[m$periodo >= "200607", ]

cat(sprintf("\n[2] Stats MS_BCB vs MA_BCB (n=%d):\n", nrow(m)))
cat(sprintf("    mean(MA)=%+.4f  mean(MS)=%+.4f  mean(MS-MA)=%+.4f\n",
            mean(m$ma), mean(m$ms), mean(m$diff)))
cat(sprintf("    mean|MS-MA|=%.4f  max|MS-MA|=%.4f  RMSE=%.4f\n",
            mean(abs(m$diff)), max(abs(m$diff)), sqrt(mean(m$diff^2))))

cat("\n[3] 10 maiores divergências MS_BCB - MA_BCB:\n")
ord <- order(-abs(m$diff))
print(head(m[ord, ], 10), row.names=FALSE)

# Agora compara nosso MS atual vs BCB MS, por mês, e vê onde diverge.
cat("\n[4] Fetch nosso recon CSV e compara vs MS BCB...\n")
recon <- read.csv("data/ipca15_pareto_recon.csv", stringsAsFactors=FALSE, encoding="UTF-8")
recon$periodo <- format(as.Date(recon$date), "%Y%m")
our_ms <- recon[recon$category_code == "nucleo_ms", c("periodo","value")]
names(our_ms)[2] <- "our_ms"
our_ma <- recon[recon$category_code == "nucleo_ma", c("periodo","value")]
names(our_ma)[2] <- "our_ma"

cmp <- Reduce(function(a,b) merge(a,b,by="periodo"), list(our_ms, our_ma, ma, ms))
cmp$diff_ms <- cmp$our_ms - cmp$ms
cmp$diff_ma <- cmp$our_ma - cmp$ma
cmp$our_ms_minus_ma <- cmp$our_ms - cmp$our_ma
cmp$bcb_ms_minus_ma <- cmp$ms - cmp$ma

cat("\n[5] Nosso (MS-MA) vs BCB (MS-MA): se padrões batem, suavização OK; se nao, lista errada.\n")
cat(sprintf("    mean(our MS-MA)=%+.4f  mean(BCB MS-MA)=%+.4f\n",
            mean(cmp$our_ms_minus_ma), mean(cmp$bcb_ms_minus_ma)))
cat(sprintf("    corr(our MS-MA, BCB MS-MA)=%.4f\n",
            cor(cmp$our_ms_minus_ma, cmp$bcb_ms_minus_ma)))

cat("\n[6] 15 piores meses MS (nosso - BCB):\n")
ord <- order(-abs(cmp$diff_ms))
print(round(head(cmp[ord, c("periodo","our_ma","ma","our_ms","ms","diff_ms","our_ms_minus_ma","bcb_ms_minus_ma")], 15), 4), row.names=FALSE)

cat("\n[7] Stats agregados:\n")
cat(sprintf("    nosso MA: mean|d|=%.4f, max|d|=%.4f\n", mean(abs(cmp$diff_ma)), max(abs(cmp$diff_ma))))
cat(sprintf("    nosso MS: mean|d|=%.4f, max|d|=%.4f\n", mean(abs(cmp$diff_ms)), max(abs(cmp$diff_ms))))
