#!/usr/bin/env Rscript
# install_r_packages.R
# Deps R dos pipelines pareto_* (IPCA, IPCA-15, CPI-U, OER regional, PCE).
# Pareado com requirements.txt da raiz: Python via pip, R via este script.
#
# Uso:
#   Rscript install_r_packages.R                        # instala/atualiza o que faltar
#   Rscript install_r_packages.R --force                # reinstala tudo (ignora versao)
#   REPO=https://cran-r.c3sl.ufpr.br Rscript install_r_packages.R   # mirror custom
#
# Proxy corporativo:
#   Se o R nao conseguir sair pra CRAN no corp, defina antes de rodar:
#     Sys.setenv(http_proxy  = "http://proxy.corp:8080")
#     Sys.setenv(https_proxy = "http://proxy.corp:8080")
#   (ou shell: `set http_proxy=...` / `export http_proxy=...`)
#   O install.packages() respeita essas env vars nativamente.
#
# Observacao sobre `seasonal` (X-13ARIMA-SEATS):
#   O pacote R `seasonal` eh wrapper puro — precisa do binario x13ashtml.exe
#   (Windows) ou x13as (Linux/Mac) separado. Download:
#     https://www.census.gov/data/software/x13as.html
#   Depois: Sys.setenv(X13_PATH = "C:/path/to/x13ashtml/")  — ou coloca no PATH.
#   Testar: library(seasonal); checkX13()
#
# Versoes referencia (testadas out/2026):
#   R         4.4.0 ucrt (ou mais novo; 4.5.x tambem funciona)
#   httr      1.4.8
#   jsonlite  1.8.8
#   seasonal  1.10.0
#   openxlsx  4.2.7.1

PACKAGES <- list(
  # pacote     versao minima (ou "" pra qualquer)   usado por
  httr      = list(min = "1.4.0",   use = "SIDRA/BCB/BLS HTTP (todos os pipelines)"),
  jsonlite  = list(min = "1.8.0",   use = "parse JSON (pareado com httr)"),
  seasonal  = list(min = "1.9.0",   use = "SA via X-13ARIMA-SEATS (nucleos IPCA DP/MS; precisa binario X-13 instalado)"),
  openxlsx  = list(min = "4.2.0",   use = "build_mapping_categoria.R (xlsx de audit)")
)

REPO <- Sys.getenv("REPO", unset = "https://cran.r-project.org")

args <- commandArgs(trailingOnly = TRUE)
force <- "--force" %in% args

cat(sprintf("[install_r_packages] R %s, repo=%s%s\n",
            getRversion(), REPO, if (force) " (--force)" else ""))

needs_install <- function(pkg, min_ver) {
  if (!requireNamespace(pkg, quietly = TRUE)) return(TRUE)
  if (!nzchar(min_ver)) return(FALSE)
  utils::compareVersion(as.character(packageVersion(pkg)), min_ver) < 0
}

to_install <- character(0)
for (pkg in names(PACKAGES)) {
  spec <- PACKAGES[[pkg]]
  cur  <- tryCatch(as.character(packageVersion(pkg)),
                   error = function(e) NA_character_)
  if (force || needs_install(pkg, spec$min)) {
    status <- if (is.na(cur)) "AUSENTE" else sprintf("v%s < min %s", cur, spec$min)
    cat(sprintf("  [%s] %-10s %s  (%s)\n",
                if (force) "FORCE" else "INSTALAR", pkg, status, spec$use))
    to_install <- c(to_install, pkg)
  } else {
    cat(sprintf("  [OK]       %-10s v%s  (%s)\n", pkg, cur, spec$use))
  }
}

if (!length(to_install)) {
  cat("\nNada a instalar. Tudo em dia.\n")
  quit(save = "no", status = 0)
}

cat(sprintf("\nInstalando %d pacote(s): %s\n",
            length(to_install), paste(to_install, collapse = ", ")))
install.packages(to_install, repos = REPO, dependencies = TRUE)

# Audit final — garante que ficou instalavel.
failed <- character(0)
for (pkg in to_install) {
  if (!requireNamespace(pkg, quietly = TRUE)) {
    failed <- c(failed, pkg)
  } else {
    cat(sprintf("  [OK pos-install] %-10s v%s\n", pkg, packageVersion(pkg)))
  }
}
if (length(failed)) {
  cat(sprintf("\n[FAIL] Nao instalou: %s\n", paste(failed, collapse = ", ")))
  cat("  Possiveis causas: proxy nao configurado, firewall corp, mirror offline.\n")
  cat("  Teste manualmente: Rscript -e 'install.packages(\"httr\")'\n")
  quit(save = "no", status = 1)
}

cat("\nOK. Pipelines prontos pra rodar.\n")
if ("seasonal" %in% to_install) {
  cat("\n[seasonal] Lembre de instalar o binario X-13ARIMA-SEATS separadamente:\n")
  cat("  https://www.census.gov/data/software/x13as.html\n")
  cat("  Depois: Sys.setenv(X13_PATH = \"C:/x13ashtml/\"); library(seasonal); checkX13()\n")
}
