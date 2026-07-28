#!/usr/bin/env Rscript
# reconstruct_ipca.R (pareto_ipca15)
#
# Reconstrói as agregações BCB do IPCA-15 (administrados, livres, industriais,
# serviços e alimentação no domicílio) a partir dos subitens publicados pelo
# IBGE em SIDRA T7062 (POF 2017-18) ou T1705 (POF 2008-09) — máscaras em
# scripts/ipca_masks/.
#
# Por que essa abordagem: mesma NT_57 do IPCA cheio, aplicada às tabelas
# SIDRA do IPCA-15. Publicação IBGE do IPCA-15 é ~dia 24; entregar os
# núcleos e agregações no mesmo dia do release.
#
# ⚠️ Único SGS legítimo pro IPCA-15 é 7478 (headline). Validação vs BCB
# fica DESLIGADA por default (rotina de atualização); opt-in via --with-bcb.
#
# Algebra (índice de Laspeyres com pesos mensais):
#
#   v_classe  = Σ(w_i × v_i, i ∈ classe)  /  Σ(w_i, i ∈ classe)
#   p_classe  = Σ(w_i, i ∈ classe)
#   v_livres  = (v_ipca × Σw - v_admin × p_admin) / p_livres   (controle algébrico)
#
# Onde w_i é o peso mensal do subitem i no IPCA total (V66 da T7060) e v_i
# é a variação mensal (V63). A validação principal é: somando todos os
# subitens com pesos próprios devemos obter o IPCA geral publicado pelo IBGE
# (até erro de arredondamento na 2ª/3ª decimal).
#
# Classes BCB (Tabela 5 do Relatório de Inflação Dez/2019):
#   monitorado            → administrados
#   alimento_domic        → alimentação no domicílio
#   alimento_fora         → alimentação fora do domicílio (entra em serviços)
#   servico               → serviços (inclui alimento_fora)
#   duravel/semiduravel/
#     nao_duravel_industrial → bens industriais
#
# Saídas:
#   scripts/outputs/ipca_reconstruido.csv     — série mensal v_ipca, v_admin, v_livres,
#                                               v_industr, v_serv, v_alim_dom (+ pesos)
#   scripts/outputs/ipca_auditoria_<MES>.csv  — detalhe subitem-a-subitem do último mês
#   scripts/outputs/ipca_validacao_bcb.csv    — headline IPCA-15 vs SGS 7478
#
# Uso:
#   cd backend
#   Rscript scripts/reconstruct_ipca.R              # roda últimos 24 meses, SEM BCB
#   Rscript scripts/reconstruct_ipca.R 202401 202604  # janela específica, SEM BCB
#   Rscript scripts/reconstruct_ipca.R --with-bcb   # opt-in: valida headline vs SGS 7478
#                                                     (rotina de atualização normal
#                                                     roda MUDA — não fetch BCB)

suppressPackageStartupMessages({
  library(httr)
  library(jsonlite)
})

# Auto-cwd: se chamado via Rscript de qualquer pasta, descobre a raiz do projeto
# (pai de scripts/) e seta como cwd. Evita "no such file" por wd errado.
.argv <- commandArgs(trailingOnly = FALSE)
.farg <- grep("^--file=", .argv, value = TRUE)
if (length(.farg)) {
  .root <- dirname(dirname(normalizePath(sub("^--file=", "", .farg[1]))))
  setwd(.root)
  cat(sprintf("[CWD] %s\n", .root))
}

# Carrega config de proxy se existir (rede institucional). Sem o arquivo
# (rodando em casa), este source vira no-op.
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

# ---------------------------------------------------------------------------
# Configuração

MASK_ADMIN_PATH <- "scripts/ipca_masks/administrados.csv"
MASK_CLASS_PATH <- Sys.getenv("MASK_CLASS_PATH_OVR",
                              unset = "scripts/ipca_masks/classificacao.csv")
OUT_DIR         <- Sys.getenv("OUT_DIR_OVR", unset = "scripts/outputs")
PARETO_BASE_CSV <- Sys.getenv("PARETO_BASE_CSV_OVR",
                              unset = "data/ipca15_pareto_recon.csv")
dir.create(dirname(PARETO_BASE_CSV), showWarnings = FALSE, recursive = TRUE)
# Default T7062 (IPCA-15 POF 2017-18, fev/2020+). Análogo IPCA-15 da T7060.
SIDRA_AGG       <- as.integer(Sys.getenv("SIDRA_AGG_ID", unset = "7062"))
SKIP_PARETO_UPDATE <- nzchar(Sys.getenv("SKIP_PARETO_UPDATE", unset = ""))
# IDs de variavel divergem entre agregados:
#   IPCA cheio (T7060/T1419/T2938): V63 (var mensal), V66 (peso mensal)
#   IPCA-15    (T7062/T1705):       V355 (var mensal), V357 (peso mensal)
# Default aqui e' IPCA-15 (V355/V357). Overrideavel via env pra reusar no cheio.
SIDRA_VAR_VAR   <- as.integer(Sys.getenv("SIDRA_VAR_VAR",  unset = "355"))
SIDRA_VAR_PESO  <- as.integer(Sys.getenv("SIDRA_VAR_PESO", unset = "357"))
SIDRA_CLS       <- 315L   # geral/grupos/subgrupos/itens/subitens (mesmo codigo em ambos)

# ---------------------------------------------------------------------------
# BCB SGS — só o headline IPCA-15 (7478) tem código público.
# Breakdowns IPCA-15 não existem como SGS (probe 2026-07-27, `_probe_score.py`
# sobre ~230 candidatos). Comparação vs SGS de IPCA cheio é gap metodológico,
# não validação — feita sob demanda em `_audit_ibge_vs_bcb.R`, fora do pipeline.

BCB_SGS_IPCA15_TOTAL <- 7478L
TOL_VALIDACAO   <- 0.05   # divergência aceitável em pp/mês na recomposição do IPCA

# Lista de ITENS (nchar=4) com variação suavizada no MS — NT_57/Dez-2025
# Tabela 5, estrutura vigente desde jan/2020: BCB substitui a variação mensal
# desses 9 ITENS pela média geométrica dos últimos 12 meses antes de aplicar
# o trim 20/80 a nível ITEM. Fórmula (nota 11): π_i^12m = 100·[Π(1+π/100)]^(1/12) − 1
MS_ITEMS_SUAV <- c(
  "2201",  # Combustíveis (domésticos)
  "2202",  # Energia elétrica residencial
  "5101",  # Transporte público
  "5104",  # Combustíveis (veículos)
  "7101",  # Serviços pessoais
  "7202",  # Fumo
  "8101",  # Cursos regulares
  "8104",  # Cursos diversos
  "9101"   # Comunicação
)

# NT_57 Sec 2.1.1 — EX-FE (ex food and energy, COICOP). Exclui:
#   - subgrupo 11 (Alimentação no domicílio), exceto bebidas alcoólicas
#   - subgrupo 22 (Combustíveis e energia)
#   - subitem 5102007 (Óleo lubrificante)
#   - item    5104    (Combustíveis veículos)
# Bebidas alcoólicas no IPCA: subitens 1114003 (Bebidas alcoólicas) +
# possivelmente outros. Mantemos no EX-FE.
EXFE_EXCL_SUBGRUPOS  <- c("11", "22")
EXFE_EXCL_SUBITENS   <- c("5102007")
EXFE_EXCL_ITENS      <- c("5104")
EXFE_KEEP_SUBITENS   <- c("1114003")  # bebidas alcoólicas — não excluir
# Lista oficial em SIDRA pode usar subitens diferentes pra bebida alcoólica;
# refinar empiricamente se diff vs SGS 28751 ficar > 0.05pp.

# RI Dez/2019 Tab.3 — reclassificações C↔NC na migração POF 2008-09→2017-18.
# Laticínios (exceto leite em pó 1111009) e panificados frescos: C → NC.
# Frutas (item 1106, todos 1106xxx): NC → C.
# Aplicadas SÓ na máscara base (T7060/POF 2017-18); na extended (T2938/T1419)
# usa a classificação vigente em cada POF (laticínios eram C, frutas eram NC).
COMERC_EXCL_NC_POF1718 <- c(
  "1111004",  # Leite longa vida
  "1111008",  # Leite condensado
  "1111011",  # Queijo
  "1111019",  # Iogurte e bebidas lácteas
  "1111021",  # Requeijão
  "1111031",  # Manteiga
  "1111038",  # Leite fermentado
  "1112015",  # Pão francês
  "1112017",  # Pão doce
  "1112019"   # Bolo
)
COMERC_INCL_C_ITEM_POF1718 <- "1106"  # frutas — todos os 1106xxx → C

# NT_57 Sec 2.1.1 — EX1. Exclui 12 ITENS (combustíveis + alimentos voláteis):
EX1_EXCL_ITENS <- c(
  "1101",  # Cereais, leguminosas e oleaginosas
  "1103",  # Tubérculos, raízes e legumes
  "1104",  # Açúcares e derivados
  "1105",  # Hortaliças e verduras
  "1106",  # Frutas
  "1107",  # Carnes
  "1108",  # Pescados
  "1110",  # Aves e ovos
  "1111",  # Leites e derivados
  "1113",  # Óleos e gorduras
  "2201",  # Combustíveis (domésticos)
  "5104"   # Combustíveis (veículos)
)

dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

# ---------------------------------------------------------------------------
# Janela de períodos (YYYYMM). Default: últimos 24 meses.

args <- commandArgs(trailingOnly = TRUE)
# Default: NÃO valida contra BCB (rotina de atualização roda muda — SGS 7478
# só publica D+1 mesmo, e o único SGS legítimo pro IPCA-15 é o headline). Pra
# validar sob demanda passe --with-bcb (ou env WITH_BCB_VALIDATION=1, que o
# seed_ibge_history.R propaga aos subprocessos quando invocado com --with-bcb).
# --no-bcb aceito como no-op pra retrocompat com scripts externos.
WITH_BCB <- ("--with-bcb" %in% args) || nzchar(Sys.getenv("WITH_BCB_VALIDATION", unset = ""))
SKIP_BCB <- !WITH_BCB
args <- args[!(args %in% c("--with-bcb", "--no-bcb"))]
if (length(args) >= 2) {
  PERIODO_INI <- as.integer(args[[1]])
  PERIODO_FIM <- as.integer(args[[2]])
} else {
  hoje <- Sys.Date()
  ref  <- seq(hoje, by = "-1 month", length.out = 25)
  ymd <- function(d) as.integer(format(d, "%Y%m"))
  PERIODO_FIM <- ymd(ref[2])   # mês passado (mês corrente raramente publicado)
  PERIODO_INI <- ymd(ref[25])
}
cat(sprintf("[CFG] janela: %d → %d\n", PERIODO_INI, PERIODO_FIM))
cat(sprintf("[CFG] validação BCB: %s\n",
            if (SKIP_BCB) "desligada (default; use --with-bcb pra ativar)" else "LIGADA"))

# ---------------------------------------------------------------------------
# Helpers

sidra_url <- function(agg, periodos, var, cls = NULL, cats = NULL) {
  base <- sprintf("https://servicodados.ibge.gov.br/api/v3/agregados/%d/periodos/%s/variaveis/%d?localidades=N1[all]",
                  agg, periodos, var)
  if (!is.null(cls)) {
    cat_str <- if (is.null(cats)) "all" else paste(cats, collapse = ",")
    base <- paste0(base, sprintf("&classificacao=%d[%s]", cls, cat_str))
  }
  base
}

# Fetch helper com retry (3 tentativas, 15s/30s de backoff) e parsing pra
# long format (periodo, cod_ibge, valor). IBGE/SIDRA às vezes retorna XML de
# erro (servidor sobrecarregado, rate-limit) mesmo com HTTP 200 — detectado
# via startsWith("<") antes de tentar fromJSON.
fetch_sidra <- function(var_id, label, periodo_str, max_tries = 3L) {
  url <- sidra_url(SIDRA_AGG, periodo_str, var_id, SIDRA_CLS, NULL)
  cat(sprintf("[GET] %s V%d ...\n", label, var_id))
  txt <- NULL
  for (attempt in seq_len(max_tries)) {
    if (attempt > 1L) {
      wait <- 15L * (attempt - 1L)
      cat(sprintf("    [retry %d/%d] aguardando %ds...\n", attempt, max_tries, wait))
      Sys.sleep(wait)
    }
    r <- GET(url, timeout(120))
    if (status_code(r) != 200) {
      cat(sprintf("    HTTP %d na tentativa %d\n", status_code(r), attempt))
      if (attempt == max_tries)
        stop(sprintf("SIDRA V%d falhou: HTTP %d após %d tentativas", var_id, status_code(r), max_tries))
      next
    }
    candidate <- content(r, "text", encoding = "UTF-8")
    if (startsWith(trimws(candidate), "<")) {
      cat(sprintf("    SIDRA retornou XML na tentativa %d (servidor sobrecarregado?)\n", attempt))
      cat(sprintf("    Início: %.120s\n", candidate))
      if (attempt == max_tries)
        stop(sprintf("SIDRA V%d retornou XML após %d tentativas — tente novamente mais tarde", var_id, max_tries))
      next
    }
    txt <- candidate
    break
  }
  raw <- fromJSON(txt, simplifyDataFrame = FALSE)
  rows <- list()
  for (var_node in raw) {
    for (res_node in var_node$resultados) {
      # cada res_node tem classificacoes[[1]]$categoria (lista 1 elemento; a categoria
      # da classificacao 315 — pode ser geral/grupo/.../subitem)
      cls <- res_node$classificacoes[[1]]
      # categoria é uma lista nomeada onde o NOME é o id da categoria (string).
      cat_id <- names(cls$categoria)[[1]]
      cat_nome <- cls$categoria[[1]]
      for (s in res_node$series) {
        # `s$serie` é uma lista nomeada com período → valor
        per_keys <- names(s$serie)
        per_vals <- as.character(unlist(s$serie))
        for (k in seq_along(per_keys)) {
          rows[[length(rows) + 1]] <- list(
            periodo  = per_keys[[k]],
            cat_id   = cat_id,
            cat_nome = cat_nome,
            valor    = per_vals[[k]]
          )
        }
      }
    }
  }
  df <- data.frame(
    periodo  = sapply(rows, function(x) x$periodo),
    cat_id   = sapply(rows, function(x) x$cat_id),
    cat_nome = sapply(rows, function(x) x$cat_nome),
    valor    = sapply(rows, function(x) x$valor),
    stringsAsFactors = FALSE
  )
  df$valor <- suppressWarnings(as.numeric(df$valor))   # "..." vira NA
  df
}

# Gera string SIDRA pros períodos. Aceita range simples YYYYMM-YYYYMM.
periodos_string <- function(ini, fim) {
  sprintf("%d-%d", ini, fim)
}

fetch_bcb_sgs <- function(code) {
  cat(sprintf("[GET] BCB SGS %d ...\n", code))
  url <- sprintf("https://api.bcb.gov.br/dados/serie/bcdata.sgs.%d/dados?formato=json", code)
  r <- GET(url, timeout(60))
  if (status_code(r) != 200) {
    warning(sprintf("BCB SGS %d falhou: HTTP %d", code, status_code(r)))
    return(data.frame(periodo = character(), valor = numeric()))
  }
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = TRUE)
  raw$periodo <- format(as.Date(raw$data, format = "%d/%m/%Y"), "%Y%m")
  raw$valor   <- as.numeric(raw$valor)
  raw[, c("periodo", "valor")]
}

# Mapeia código IBGE estruturado (prefixo numérico do nome) a partir do nome SIDRA.
extrair_cod_ibge <- function(nome) {
  prefixo <- sub("^([0-9]+)\\..*$", "\\1", nome)
  ifelse(prefixo == nome, NA_character_, prefixo)
}

# ---------------------------------------------------------------------------
# Helpers para núcleos estatísticos (Onda 4)

# Média truncada ponderada: ordena (vars) por valor crescente, computa peso
# cumulativo normalizado, e considera apenas a fatia [lower, upper] da
# distribuição de peso. Itens nas bordas entram proporcionalmente à
# sobreposição do seu intervalo [cum_start, cum_end] com [lower, upper].
# É a definição operacional do BCB para MA (20/80) e MS (20/80 + suavização
# prévia em subitens listados).
trimmed_mean <- function(vars, pesos, lower = 0.20, upper = 0.80) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  vars <- vars[ok]; pesos <- pesos[ok]
  if (!length(vars)) return(NA_real_)
  ord <- order(vars)
  vars <- vars[ord]; pesos <- pesos[ord]
  total_peso <- sum(pesos)
  if (total_peso <= 0) return(NA_real_)
  cum_end   <- cumsum(pesos) / total_peso
  cum_start <- cum_end - pesos / total_peso
  eff_lower <- pmax(cum_start, lower)
  eff_upper <- pmin(cum_end,   upper)
  overlap   <- pmax(eff_upper - eff_lower, 0)
  denom <- sum(overlap)
  if (denom <= 0) return(NA_real_)
  sum(vars * overlap) / denom
}

# Média ponderada simples (pra DP, depois de re-pesar pelos inversos de
# volatilidade). Não trunca — DP usa universo cheio.
weighted_mean_simple <- function(vars, pesos) {
  ok <- !is.na(vars) & !is.na(pesos) & pesos > 0
  if (!any(ok)) return(NA_real_)
  sum(vars[ok] * pesos[ok]) / sum(pesos[ok])
}

# ---------------------------------------------------------------------------
# 1. Carrega máscaras

cat("\n[1] Carregando máscaras...\n")
mask_admin <- read.csv(MASK_ADMIN_PATH, stringsAsFactors = FALSE, encoding = "UTF-8")
mask_admin$cod_ibge <- as.character(mask_admin$cod_ibge)
cat(sprintf("    administrados:  %d subitens\n", nrow(mask_admin)))

mask_class <- read.csv(MASK_CLASS_PATH, stringsAsFactors = FALSE, encoding = "UTF-8")
mask_class$cod_ibge <- as.character(mask_class$cod_ibge)
cat(sprintf("    classificação: %d subitens\n", nrow(mask_class)))
cat("    distribuição de classes:\n")
print(table(mask_class$classe))

# ---------------------------------------------------------------------------
# 2. Fetch dados SIDRA

cat(sprintf("\n[2] Fetch dados SIDRA T%d...\n", SIDRA_AGG))
per_str <- periodos_string(PERIODO_INI, PERIODO_FIM)
df_var  <- fetch_sidra(SIDRA_VAR_VAR,  "variação mensal", per_str)
df_peso <- fetch_sidra(SIDRA_VAR_PESO, "peso mensal",      per_str)

df_var$cod_ibge  <- extrair_cod_ibge(df_var$cat_nome)
df_peso$cod_ibge <- extrair_cod_ibge(df_peso$cat_nome)

cat(sprintf("    variações: %d linhas (categorias × períodos)\n", nrow(df_var)))
cat(sprintf("    pesos:     %d linhas\n", nrow(df_peso)))

# Merge num único frame: (periodo, cod_ibge, cat_nome, var, peso)
df <- merge(df_var[, c("periodo", "cod_ibge", "cat_nome", "valor")],
            df_peso[, c("periodo", "cod_ibge", "valor")],
            by = c("periodo", "cod_ibge"), suffixes = c("_var", "_peso"))
names(df)[names(df) == "valor_var"]  <- "var_mm"
names(df)[names(df) == "valor_peso"] <- "peso_mm"

# Marca subitens (cod_ibge de 7 dígitos) — único nível que tem peso individual
# pra agregação ponderada.
df$nchar_cod <- nchar(df$cod_ibge)
df$tipo_cat <- ifelse(is.na(df$cod_ibge), "geral",
                ifelse(df$nchar_cod == 7, "subitem",
                  ifelse(df$nchar_cod == 4, "item",
                    ifelse(df$nchar_cod == 2, "subgrupo",
                      ifelse(df$nchar_cod == 1, "grupo", "outro")))))
df$is_admin <- !is.na(df$cod_ibge) & df$cod_ibge %in% mask_admin$cod_ibge

# Merge classe BCB pra cada subitem
df <- merge(df, mask_class[, c("cod_ibge", "classe", "subjacente", "proc_grau",
                                "bens_industriais")],
            by = "cod_ibge", all.x = TRUE)

cat(sprintf("    distribuição tipo_cat:\n"))
print(table(df$tipo_cat, useNA = "ifany"))
cat(sprintf("    subitens marcados como admin: %d (esperado: %d × %d meses = %d)\n",
            sum(df$is_admin), nrow(mask_admin),
            length(unique(df$periodo)), nrow(mask_admin) * length(unique(df$periodo))))

# ---------------------------------------------------------------------------
# 3. Validação base: soma ponderada de subitens deve bater com IPCA geral

cat("\n[3] Validação base: somatório dos subitens vs IPCA geral...\n")

ipca_geral <- df[df$tipo_cat == "geral", c("periodo", "var_mm")]
names(ipca_geral)[2] <- "ipca_oficial"

subi <- df[df$tipo_cat == "subitem", ]
agg_check <- aggregate(cbind(prod = subi$var_mm * subi$peso_mm,
                              w    = subi$peso_mm),
                       by = list(periodo = subi$periodo),
                       FUN = sum, na.rm = TRUE)
agg_check$ipca_reconstr <- agg_check$prod / agg_check$w
agg_check <- merge(agg_check[, c("periodo", "w", "ipca_reconstr")],
                   ipca_geral, by = "periodo")
agg_check$diff <- agg_check$ipca_reconstr - agg_check$ipca_oficial

cat("    pesos somam por mês (deveriam dar ~100):\n")
print(agg_check[, c("periodo", "w")], row.names = FALSE)
cat("\n    IPCA reconstruído vs publicado:\n")
chk <- agg_check[, c("periodo", "ipca_reconstr", "ipca_oficial", "diff")]
chk[, -1] <- round(chk[, -1], 4)
print(chk, row.names = FALSE)

if (any(abs(agg_check$diff) > TOL_VALIDACAO, na.rm = TRUE)) {
  warning(sprintf("Divergência > %.3fpp em algum mês — máscara/dados podem estar inconsistentes.",
                  TOL_VALIDACAO))
}

# ---------------------------------------------------------------------------
# 4. Reconstrução: administrados + livres

cat("\n[4] Computando administrados e livres por mês...\n")

# admin subset
admin <- subi[subi$is_admin, ]
livres_subi <- subi[!subi$is_admin, ]

calc_agg <- function(d) {
  data.frame(
    periodo = sort(unique(d$periodo)),
    var_mm  = sapply(sort(unique(d$periodo)), function(p) {
      x <- d[d$periodo == p, ]
      sum(x$var_mm * x$peso_mm, na.rm = TRUE) / sum(x$peso_mm, na.rm = TRUE)
    }),
    peso    = sapply(sort(unique(d$periodo)), function(p) {
      sum(d[d$periodo == p, "peso_mm"], na.rm = TRUE)
    }),
    stringsAsFactors = FALSE
  )
}

agg_admin  <- calc_agg(admin)
agg_livres <- calc_agg(livres_subi)
names(agg_admin)[2:3]  <- c("var_admin",  "peso_admin")
names(agg_livres)[2:3] <- c("var_livres", "peso_livres")

# Industriais (Duráveis + Semi-duráveis + Não-duráveis industriais — exclui
# alimentação no domicílio, monitorados e serviços por construção da máscara).
industr_subi <- subi[!is.na(subi$bens_industriais) & subi$bens_industriais, ]
agg_industr  <- calc_agg(industr_subi)
names(agg_industr)[2:3] <- c("var_industr", "peso_industr")

# Serviços (inclui alimento_fora — Tabela 5 trata como serviço).
serv_subi <- subi[!is.na(subi$classe) & subi$classe %in% c("servico", "alimento_fora"), ]
agg_serv  <- calc_agg(serv_subi)
names(agg_serv)[2:3] <- c("var_serv", "peso_serv")

# Alimentação no domicílio (subgrupo 11).
alim_dom_subi <- subi[!is.na(subi$classe) & subi$classe == "alimento_domic", ]
agg_alim_dom  <- calc_agg(alim_dom_subi)
names(agg_alim_dom)[2:3] <- c("var_alim_dom", "peso_alim_dom")

# Núcleo EX0 — exclui monitorados E alimentos no domicílio. Definição BCB
# (RI Dez/2019, Tab.5; SGS 11427). Reusa máscaras existentes: subitens que
# NÃO são admin E NÃO são alimento_domic.
nucleo_ex0_subi <- subi[!subi$is_admin &
                          (is.na(subi$classe) | subi$classe != "alimento_domic"), ]
agg_nucleo_ex0  <- calc_agg(nucleo_ex0_subi)
names(agg_nucleo_ex0)[2:3] <- c("var_nucleo_ex0", "peso_nucleo_ex0")

# Núcleo EX3 — exclui (Tab.5 RI Dez/2019; SGS 27839):
#   - Alimentação no domicílio (classe alimento_domic)
#   - Aparelhos eletroeletrônicos (subgrupo 32, cod_ibge ^32xxxxx)
#   - Automóvel novo (5102001), Automóvel usado (5102020)
#   - Etanol (5104002), Fumo (7202041 cigarro)
#   - Serviços Ex-Subjacente (classe servico & subjacente == FALSE)
#   - Monitorados (is_admin)
APARELHOS_ELETRO_PREFIX <- "32"   # subgrupo 32: 7 dígitos começando com 32
EX3_EXCL_CODES <- c("5102001", "5102020", "5104002", "7202041")

ex3_excl <- subi$is_admin |
            (!is.na(subi$classe) & subi$classe == "alimento_domic") |
            (!is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 2) == APARELHOS_ELETRO_PREFIX) |
            (!is.na(subi$cod_ibge) & subi$cod_ibge %in% EX3_EXCL_CODES) |
            (!is.na(subi$classe) & subi$classe == "servico" &
             !is.na(subi$subjacente) & !subi$subjacente)
nucleo_ex3_subi <- subi[!ex3_excl, ]
agg_nucleo_ex3  <- calc_agg(nucleo_ex3_subi)
names(agg_nucleo_ex3)[2:3] <- c("var_nucleo_ex3", "peso_nucleo_ex3")

# Onda 3a — bens duráveis / semi-duráveis / não-duráveis industriais.
# Decomposição da classe `industrial` da Tab.5 (BCB SGS 10843/10842/parcial-10841).
# ND-industrial isolado não tem SGS direto; a soma com alim_in_natura+alim_semi_elab
# (Onda 3c) compõe SGS 10841 (Bens não-duráveis BCB).
duravel_subi <- subi[!is.na(subi$classe) & subi$classe == "duravel", ]
agg_duravel  <- calc_agg(duravel_subi)
names(agg_duravel)[2:3] <- c("var_duravel", "peso_duravel")

semidur_subi <- subi[!is.na(subi$classe) & subi$classe == "semiduravel", ]
agg_semidur  <- calc_agg(semidur_subi)
names(agg_semidur)[2:3] <- c("var_semidur", "peso_semidur")

ndind_subi <- subi[!is.na(subi$classe) & subi$classe == "nao_duravel_industrial", ]
agg_ndind  <- calc_agg(ndind_subi)
names(agg_ndind)[2:3] <- c("var_ndind", "peso_ndind")

# Onda 3b — Serviços Subjacente vs Ex-Subjacente.
# Definição BCB (Tab.5 RI Dez/2019): subjacente=TRUE inclui 36 serviços + alim_fora;
# ex-subjacente são serviços remanescentes (passagens, hospedagem, cursos, telecom).
# SUBJ + EXSUBJ = SERV total = SGS 10840 (validado por consistência interna).
serv_subj_subi <- subi[!is.na(subi$classe) & subi$classe %in% c("servico", "alimento_fora") &
                       !is.na(subi$subjacente) & subi$subjacente, ]
agg_serv_subj  <- calc_agg(serv_subj_subi)
names(agg_serv_subj)[2:3] <- c("var_serv_subj", "peso_serv_subj")

serv_exsubj_subi <- subi[!is.na(subi$classe) & subi$classe == "servico" &
                         !is.na(subi$subjacente) & !subi$subjacente, ]
agg_serv_exsubj  <- calc_agg(serv_exsubj_subi)
names(agg_serv_exsubj)[2:3] <- c("var_serv_exsubj", "peso_serv_exsubj")

# Onda 3c — Alimentos no domicílio por grau de processamento.
# Classificação por proc_grau lido da máscara, seguindo BCB RI Dez/2019 Tab.5:
#   in_natura = Tubérculos/raízes/legumes (1103) + Hortaliças/verduras (1105)
#               + Frutas (1106) + Ovo de galinha (1110044)
#   semi_elab = Cereais/leguminosas/oleaginosas (1101) + Carnes (1107)
#               + Pescados (1108) + Frango inteiro (1110009)
#               + Frango em pedaços (1110010) + Leite longa vida (1111004)
#   industr   = Farinhas/féculas/massas (1102) + Açúcares/derivados (1104)
#               + Carnes e peixes industrializados (1109)
#               + Leite e derivados exceto Leite longa vida (1111\\1111004)
#               + Panificados (1112) + Óleos/gorduras (1113)
#               + Bebidas/infusões (1114) + Enlatados/conservas (1115)
#               + Sal e condimentos (1116)
#
# BCB não publica essas decomposições como SGS público — comparação direta
# impossível. SGS 1635/1636/1637 (que parecem candidatos pelo nome no
# código antigo do projeto) são, na verdade, os GRUPOS 1/2/3 top-level do
# IPCA: "Alimentação e bebidas", "Habitação", "Artigos de residência"
# (provado por diff=0, corr=1 contra IBGE T7060 cat 7170/7445/...). Varredura
# de 190 códigos plausíveis: 0 hits. Nossa recon é a única série publicada
# que aplica Tab.5 estritamente a partir do detalhe subitem do IBGE.
alim_in_subi <- subi[!is.na(subi$proc_grau) & subi$proc_grau == "in_natura", ]
agg_alim_in  <- calc_agg(alim_in_subi)
names(agg_alim_in)[2:3] <- c("var_alim_in", "peso_alim_in")

alim_se_subi <- subi[!is.na(subi$proc_grau) & subi$proc_grau == "semi_elab", ]
agg_alim_se  <- calc_agg(alim_se_subi)
names(agg_alim_se)[2:3] <- c("var_alim_se", "peso_alim_se")

alim_ind_subi <- subi[!is.na(subi$proc_grau) & subi$proc_grau == "industr", ]
agg_alim_ind  <- calc_agg(alim_ind_subi)
names(agg_alim_ind)[2:3] <- c("var_alim_ind", "peso_alim_ind")

# Onda 3d — Comercializáveis vs Não-Comercializáveis.
# Definição BCB (RI Dez/2019 Tab.5/6, SGS 4447/4448):
#   IPCA = COMERC + NCOMERC + MONITORADOS (três categorias, não binário)
#   COMERC   = bens industriais + alim_industr + alim_semi_elab
#   NCOMERC  = serviços (incl. alim_fora) + alim in-natura
#   MONITORADOS = preços administrados (SGS 4449 — categoria separada)
# Monitorados NÃO entram em COMERC nem NCOMERC.
# RI Dez/2019 Tab.3 — tratamento híbrido calibrado contra BCB SGS 4447/4448:
#   Frutas (1106xxx) → C retroativamente em toda janela (BCB aplica assim no SGS).
#   Laticínios/panificados → NC apenas na máscara base (T7060/2020+); BCB mantém
#   esses itens em C na série histórica (SGS 4447 pré-2020 os trata como C).
# Identidade: peso_comerc + peso_ncomerc + peso_admin ≈ 100.
is_extended_mask <- grepl("extended", MASK_CLASS_PATH, ignore.case = TRUE)
.comerc_excl      <- if (is_extended_mask) character(0) else COMERC_EXCL_NC_POF1718
.comerc_incl_item <- COMERC_INCL_C_ITEM_POF1718   # frutas → C em toda janela

comerc_subi <- subi[
  !subi$is_admin &
  !(!is.na(subi$cod_ibge) & subi$cod_ibge %in% .comerc_excl) &
  ((!is.na(subi$bens_industriais) & subi$bens_industriais) |
   (!is.na(subi$proc_grau) & subi$proc_grau %in% c("industr", "semi_elab")) |
   (nzchar(.comerc_incl_item) & !is.na(subi$cod_ibge) &
    substr(subi$cod_ibge, 1, 4) == .comerc_incl_item)), ]
agg_comerc  <- calc_agg(comerc_subi)
names(agg_comerc)[2:3] <- c("var_comerc", "peso_comerc")

ncomerc_subi <- subi[
  !subi$is_admin &
  !(nzchar(.comerc_incl_item) & !is.na(subi$cod_ibge) &
    substr(subi$cod_ibge, 1, 4) == .comerc_incl_item) &
  ((!is.na(subi$classe) & subi$classe %in% c("servico", "alimento_fora")) |
   (!is.na(subi$proc_grau) & subi$proc_grau == "in_natura") |
   (!is.na(subi$cod_ibge) & subi$cod_ibge %in% .comerc_excl)), ]
agg_ncomerc  <- calc_agg(ncomerc_subi)
names(agg_ncomerc)[2:3] <- c("var_ncomerc", "peso_ncomerc")

# Onda 4 — Núcleos estatísticos MS / MA / DP.
# Universo: TODOS os ITENS (nchar=4, ~51 itens) — não subitens. EE102 nota 2:
# "O núcleo por médias aparadas (MA) exclui os ITENS cuja variação mensal se
# situe acima do p80 ou abaixo do p20. Os 60% restantes são utilizados...".
# Contraste com P55 (nota 3): "abertura por SUBITEM... maior granularidade".
# Validado empiricamente: trim 20/80 a nível item bate BCB SGS 11426 com
# mean|d|=0.0025pp, max|d|=0.0049pp em 76 meses 2020-01..2026-04.

cat("\n[4b] Computando núcleos estatísticos MA/MS/DP por mês (nível ITEM)...\n")

itm <- df[df$tipo_cat == "item", ]
cat(sprintf("    universo item: %d itens × %d meses = %d linhas\n",
            length(unique(itm$cod_ibge)), length(unique(itm$periodo)), nrow(itm)))

periodos_ord <- sort(unique(itm$periodo))

# ---- MA: média truncada 20/80 sem suavização ----
agg_nucleo_ma <- data.frame(
  periodo = periodos_ord,
  var_nucleo_ma = sapply(periodos_ord, function(p) {
    x <- itm[itm$periodo == p, ]
    trimmed_mean(x$var_mm, x$peso_mm, lower = 0.20, upper = 0.80)
  }),
  stringsAsFactors = FALSE
)

# ---- MS: 9 itens com variação suavizada via média geométrica 12m, depois trim ----
# NT_57/Dez-2025 Sec 2.4 + Tabela 5: opera a nível ITEM (não subitem). Pros 9
# itens em MS_ITEMS_SUAV, substitui var_mm pela média geométrica dos últimos 12
# meses: π_i^12m = 100·[Π(1+π/100)]^(1/12) − 1 (footnote 11). Pros demais usa
# var original. Em seguida aplica trim 20/80 igual MA.
# Warm-up: primeiros 11 meses usam janela expansiva {1..i} pra evitar NA.
itm_ms <- itm[order(itm$cod_ibge, itm$periodo), ]
codes_suav <- intersect(MS_ITEMS_SUAV, unique(itm_ms$cod_ibge))
cat(sprintf("    MS: %d / %d itens da lista oficial NT_57 disponíveis em SIDRA\n",
            length(codes_suav), length(MS_ITEMS_SUAV)))

for (cod in codes_suav) {
  idx <- which(itm_ms$cod_ibge == cod)
  if (!length(idx)) next
  v <- itm_ms$var_mm[idx]
  v_smooth <- rep(NA_real_, length(v))
  for (i in seq_along(v)) {
    lo <- max(1L, i - 11L)
    w <- v[lo:i]
    w <- w[!is.na(w)]
    if (length(w) >= 1L) {
      v_smooth[i] <- 100 * ((prod(1 + w / 100))^(1 / length(w)) - 1)
    }
  }
  itm_ms$var_mm[idx] <- v_smooth
}

agg_nucleo_ms <- data.frame(
  periodo = periodos_ord,
  var_nucleo_ms = sapply(periodos_ord, function(p) {
    x <- itm_ms[itm_ms$periodo == p, ]
    trimmed_mean(x$var_mm, x$peso_mm, lower = 0.20, upper = 0.80)
  }),
  stringsAsFactors = FALSE
)

# ---- DP: dupla ponderação — peso final = peso_orig / sigma_k,t-1 ----
# NT_57/Dez-2025 Sec 2.2: σ_k,t-1 = desvio padrão de (var_item_k − var_IPCA_cheio)
# em janela móvel de 48 meses terminando em t-1 (exclui o mês corrente). Mede
# o ruído ITEM-ESPECÍFICO em relação à inflação geral, não a volatilidade
# absoluta do item.
# Warm-up: pros primeiros DP_WIN meses, usa janela expansiva {1..t-1} com
# mínimo DP_MIN observações. NT_57 menciona proxies pras transições POF mas
# como nossa série começa em 2006-07 já com POF 2002-03, isso só afetaria
# pequena janela na transição POF 02-03→08-09 (jan/2012) e 08-09→17-18 (jan/2020).
DP_WIN <- 48L
DP_MIN <- 6L

ipca_per <- df[df$tipo_cat == "geral", c("periodo", "var_mm")]
names(ipca_per)[2] <- "var_ipca"
itm_dp <- merge(itm, ipca_per, by = "periodo", all.x = TRUE)
itm_dp$diff_ipca <- itm_dp$var_mm - itm_dp$var_ipca
itm_dp <- itm_dp[order(itm_dp$cod_ibge, itm_dp$periodo), ]

agg_nucleo_dp <- data.frame(
  periodo = periodos_ord,
  var_nucleo_dp = NA_real_,
  stringsAsFactors = FALSE
)

for (k in seq_along(periodos_ord)) {
  p <- periodos_ord[k]
  if (k < 2L) next   # 1º mês: sem janela passada
  k_hi <- k - 1L
  k_lo <- max(1L, k - DP_WIN)
  pers_win <- periodos_ord[k_lo:k_hi]
  win <- itm_dp[itm_dp$periodo %in% pers_win, ]
  sigmas <- aggregate(
    diff_ipca ~ cod_ibge, data = win,
    FUN = function(v) {
      v <- v[!is.na(v)]
      if (length(v) < DP_MIN) return(NA_real_)
      sd(v)
    }
  )
  names(sigmas)[2] <- "sigma"
  x <- itm_dp[itm_dp$periodo == p, ]
  x <- merge(x, sigmas, by = "cod_ibge", all.x = TRUE)
  x <- x[!is.na(x$sigma) & x$sigma > 1e-6, ]
  if (!nrow(x)) next
  wt <- x$peso_mm / x$sigma
  agg_nucleo_dp$var_nucleo_dp[k] <- weighted_mean_simple(x$var_mm, wt)
}

# ---------------------------------------------------------------------------
# Onda 5 — Núcleos por exclusão NT_57 + Difusão.

cat("\n[4c] Computando núcleos NT_57: EX-FE, EX1, EX3 Serv/Ind + Difusão...\n")

# Núcleo EX-FE — exclui alim_dom (exceto bebidas alcoólicas), combust. e energia,
# óleo lubrificante (5102007) e combustíveis veículos (5104).
# Subgrupo = primeiros 2 chars do cod_ibge (subitem nchar=7).
exfe_excl <- (!is.na(subi$cod_ibge) &
                substr(subi$cod_ibge, 1, 2) %in% EXFE_EXCL_SUBGRUPOS &
                !subi$cod_ibge %in% EXFE_KEEP_SUBITENS) |
             (!is.na(subi$cod_ibge) & subi$cod_ibge %in% EXFE_EXCL_SUBITENS) |
             (!is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 4) %in% EXFE_EXCL_ITENS)
nucleo_exfe_subi <- subi[!exfe_excl, ]
agg_nucleo_exfe  <- calc_agg(nucleo_exfe_subi)
names(agg_nucleo_exfe)[2:3] <- c("var_nucleo_exfe", "peso_nucleo_exfe")

# Núcleo EX1 — exclui 12 itens voláteis (combustíveis + alimentos sazonais).
ex1_excl <- !is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 4) %in% EX1_EXCL_ITENS
nucleo_ex1_subi <- subi[!ex1_excl, ]
agg_nucleo_ex1  <- calc_agg(nucleo_ex1_subi)
names(agg_nucleo_ex1)[2:3] <- c("var_nucleo_ex1", "peso_nucleo_ex1")

# EX3 Serviços — subjacente de serviços EXCLUINDO alim_fora (estrito EX3:
# EX3 exclui todo alimento, e alim_fora é alimento). Distinto do nosso
# `serv_subj` (Núcleo Subjacente de Serviços tradicional do BCB, que INCLUI
# alim_fora). Sem alim_fora, fica restrito a classe `servico` com flag
# subjacente=TRUE.
ex3_serv_subi <- subi[!is.na(subi$classe) & subi$classe == "servico" &
                      !is.na(subi$subjacente) & subi$subjacente, ]
agg_ex3_serv  <- calc_agg(ex3_serv_subi)
names(agg_ex3_serv)[2:3] <- c("var_ex3_serv", "peso_ex3_serv")

# EX3 Industriais = bens industriais EX (aparelhos eletro, auto novo/usado,
# etanol, cigarro/fumo) — mesma exclusão do EX3 atual restrita ao universo
# bens_industriais (sem serviços, sem admin, sem alim_dom).
ex3_ind_excl <- (!is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 2) == APARELHOS_ELETRO_PREFIX) |
                (!is.na(subi$cod_ibge) & subi$cod_ibge %in% EX3_EXCL_CODES)
ex3_ind_subi <- subi[!is.na(subi$bens_industriais) & subi$bens_industriais & !ex3_ind_excl, ]
agg_ex3_ind  <- calc_agg(ex3_ind_subi)
names(agg_ex3_ind)[2:3] <- c("var_ex3_ind", "peso_ex3_ind")

# Difusão — % de subitens com var > 0 no mês (sem pesos). NT_57 Sec 2.6:
# "apenas os subitens efetivamente pesquisados em cada mês são considerados".
# Subitens não-pesquisados aparecem como NA em var_mm (do "..." do IBGE).
agg_difusao <- data.frame(
  periodo = sort(unique(subi$periodo)),
  var_difusao = sapply(sort(unique(subi$periodo)), function(p) {
    v <- subi$var_mm[subi$periodo == p]
    v <- v[!is.na(v)]
    if (!length(v)) return(NA_real_)
    100 * sum(v > 0) / length(v)
  }),
  stringsAsFactors = FALSE
)

# P55 — Percentil 55 ponderado da distribuição cross-section dos subitens.
# EE102/2021 (núcleo do conjunto novo BCB, SGS 28750): ordenar subitens em
# ordem crescente de var; calcular pesos acumulados normalizados; pegar var
# do primeiro subitem cuja proporção acumulada >= 0.55. Razão de 55 (vs 50):
# mediana subestima por assimetria à direita da distribuição cross-section.
agg_nucleo_p55 <- data.frame(
  periodo = sort(unique(subi$periodo)),
  var_nucleo_p55 = sapply(sort(unique(subi$periodo)), function(p) {
    x <- subi[subi$periodo == p &
              !is.na(subi$var_mm) & !is.na(subi$peso_mm) & subi$peso_mm > 0,
              c("var_mm", "peso_mm")]
    if (!nrow(x)) return(NA_real_)
    x <- x[order(x$var_mm), ]
    cumw <- cumsum(x$peso_mm) / sum(x$peso_mm)
    k <- which(cumw >= 0.55)[1]
    if (is.na(k)) return(NA_real_)
    x$var_mm[k]
  }),
  stringsAsFactors = FALSE
)

# ---------------------------------------------------------------------------
# Onda 6 — Grupos IPCA + subgrupos/itens/subitens de interesse (direto do IBGE).
# Sem reconstrução: SIDRA publica esses agregados prontos via classificacao=
# 315[all]. Extraimos var_mm / peso_mm diretamente do df para cada cod_ibge.
# Preserva merge por periodo com os demais agregados.

extrair_agg_direto <- function(codigo_ibge, var_col, peso_col) {
  d <- df[!is.na(df$cod_ibge) & df$cod_ibge == codigo_ibge,
          c("periodo", "var_mm", "peso_mm")]
  d <- d[order(d$periodo), ]
  names(d) <- c("periodo", var_col, peso_col)
  d
}

agg_g1        <- extrair_agg_direto("1",       "var_g1_alim_beb",    "peso_g1_alim_beb")
agg_g2        <- extrair_agg_direto("2",       "var_g2_habitacao",   "peso_g2_habitacao")
agg_g3        <- extrair_agg_direto("3",       "var_g3_artigos",     "peso_g3_artigos")
agg_g4        <- extrair_agg_direto("4",       "var_g4_vestuario",   "peso_g4_vestuario")
agg_g5        <- extrair_agg_direto("5",       "var_g5_transportes", "peso_g5_transportes")
agg_g7        <- extrair_agg_direto("7",       "var_g7_desp_pess",   "peso_g7_desp_pess")
agg_g8        <- extrair_agg_direto("8",       "var_g8_educacao",    "peso_g8_educacao")
agg_alim_fora <- extrair_agg_direto("12",      "var_alim_fora",      "peso_alim_fora")
agg_energia   <- extrair_agg_direto("2202",    "var_energia_el",     "peso_energia_el")
agg_pass_aer  <- extrair_agg_direto("5101010", "var_passagem_aerea", "peso_passagem_aerea")
agg_auto_novo <- extrair_agg_direto("5102001", "var_auto_novo",      "peso_auto_novo")
agg_auto_usad <- extrair_agg_direto("5102020", "var_auto_usado",     "peso_auto_usado")

# Versão alternativa: livres via álgebra residual (controle de consistência)
out <- Reduce(function(a, b) merge(a, b, by = "periodo", all = TRUE),
              list(agg_admin, agg_livres, agg_industr, agg_serv, agg_alim_dom,
                   agg_nucleo_ex0, agg_nucleo_ex3,
                   agg_duravel, agg_semidur, agg_ndind,
                   agg_serv_subj, agg_serv_exsubj,
                   agg_alim_in, agg_alim_se, agg_alim_ind,
                   agg_comerc, agg_ncomerc,
                   agg_nucleo_ma, agg_nucleo_ms, agg_nucleo_dp,
                   agg_nucleo_exfe, agg_nucleo_ex1,
                   agg_ex3_serv, agg_ex3_ind, agg_difusao,
                   agg_nucleo_p55,
                   agg_g1, agg_g2, agg_g3, agg_g4, agg_g5, agg_g7, agg_g8,
                   agg_alim_fora, agg_energia,
                   agg_pass_aer, agg_auto_novo, agg_auto_usad,
                   ipca_geral))
out$var_livres_alg <- (out$ipca_oficial * (out$peso_admin + out$peso_livres) -
                       out$var_admin * out$peso_admin) / out$peso_livres
out$diff_livres_metodos <- out$var_livres - out$var_livres_alg

# Média dos 5 núcleos do conjunto NOVO BCB (EE102/2021): EX0, EX3, MS, DP, P55.
# É a referência primária acompanhada pelo Copom no RPM ("média dos núcleos").
# BCB não publica SGS único pra ela — calcula-se a partir dos componentes.
# NOTA: o MA foi SUBSTITUÍDO pelo P55 no conjunto novo (jun/2020); não entra mais
# na média oficial.
out$var_nucleo_medio <- rowMeans(
  out[, c("var_nucleo_ex0", "var_nucleo_ex3", "var_nucleo_ms",
          "var_nucleo_dp", "var_nucleo_p55")],
  na.rm = FALSE
)

# Sanity: industriais + serviços + alim_dom + admin deve cobrir ~100 do peso
out$peso_total_classes <- out$peso_admin + out$peso_industr +
                           out$peso_serv + out$peso_alim_dom

cat("\n    Reconstrução final:\n")
recon <- out[, c("periodo", "ipca_oficial", "var_admin", "peso_admin",
                 "var_livres", "peso_livres", "var_livres_alg",
                 "diff_livres_metodos")]
recon[, -1] <- round(recon[, -1], 4)
print(recon, row.names = FALSE)

cat("\n    Classes BCB (industriais, serviços, alimento_dom):\n")
classes_print <- out[, c("periodo", "var_industr", "peso_industr",
                          "var_serv", "peso_serv",
                          "var_alim_dom", "peso_alim_dom",
                          "peso_total_classes")]
classes_print[, -1] <- round(classes_print[, -1], 4)
print(classes_print, row.names = FALSE)

# ---------------------------------------------------------------------------
# 5. Validação BCB — só o headline IPCA-15 (SGS 7478).
# Breakdowns IPCA-15 não têm SGS público; comparação vs SGS IPCA cheio é gap
# metodológico, feita sob demanda em `_audit_ibge_vs_bcb.R`.

if (SKIP_BCB) {
  cat("\n[5] Validação BCB pulada (default; use --with-bcb pra ativar).\n")
} else {

cat("\n[5] Validação IPCA-15 headline: recon vs SGS 7478...\n")
sgs_ipca15_total <- fetch_bcb_sgs(BCB_SGS_IPCA15_TOTAL)
names(sgs_ipca15_total)[2] <- "bcb_ipca15_total"
val_hdl <- merge(ipca_per, sgs_ipca15_total, by = "periodo", all.x = TRUE)
val_hdl$diff_ipca15 <- val_hdl$var_ipca - val_hdl$bcb_ipca15_total
val_hdl_print <- val_hdl
val_hdl_print[, -1] <- lapply(val_hdl_print[, -1], function(x) round(x, 4))
print(val_hdl_print, row.names = FALSE)
cat(sprintf("    erro absoluto médio HEADLINE (IPCA-15): %.4f pp\n",
            mean(abs(val_hdl$diff_ipca15), na.rm = TRUE)))
cat(sprintf("    (esperado <0.01pp — SGS 7478 = IPCA-15 oficial)\n"))

}  # fim if (!SKIP_BCB)

# ---------------------------------------------------------------------------
# 6. Auditoria do último mês: lista subitens da máscara com peso + var

ultimo <- max(out$periodo)
cat(sprintf("\n[6] Auditoria detalhada para %s:\n", ultimo))
aud <- subi[subi$periodo == ultimo & subi$is_admin,
            c("cod_ibge", "cat_nome", "var_mm", "peso_mm")]
aud$contribuicao <- aud$var_mm * aud$peso_mm
aud <- aud[order(-aud$contribuicao), ]
aud_print <- aud
aud_print[, c("var_mm", "peso_mm", "contribuicao")] <- round(
  aud_print[, c("var_mm", "peso_mm", "contribuicao")], 4)
print(aud_print, row.names = FALSE)
cat(sprintf("\n    soma de pesos da máscara: %.4f\n", sum(aud$peso_mm, na.rm = TRUE)))
cat(sprintf("    soma contribuições / soma pesos = %.4f (= var_admin)\n",
            sum(aud$contribuicao, na.rm = TRUE) / sum(aud$peso_mm, na.rm = TRUE)))

# ---------------------------------------------------------------------------
# 7. Outputs

cat("\n[7] Escrevendo CSVs...\n")
write.csv(out, file.path(OUT_DIR, "ipca_reconstruido.csv"),
          row.names = FALSE, fileEncoding = "UTF-8")
if (!SKIP_BCB) {
  write.csv(val_hdl, file.path(OUT_DIR, "ipca_validacao_bcb.csv"),
            row.names = FALSE, fileEncoding = "UTF-8")
}
write.csv(aud, file.path(OUT_DIR, sprintf("ipca_auditoria_%s.csv", ultimo)),
          row.names = FALSE, fileEncoding = "UTF-8")
cat("    OK. Outputs em", OUT_DIR, "\n")

# ---------------------------------------------------------------------------
# 8. Atualiza a base servida via source=PARETO (data/ipca15_pareto_recon.csv)
#
# Formato long: (date, category_code, value). Faz merge com o arquivo
# existente — períodos recomputados sobrescrevem; períodos não cobertos
# pelo run atual preservam o histórico. Assim, rodar default (24 meses)
# atualiza só a janela recente; rodar com range explícito (ex: 202001
# 202604) reconstrói tudo dentro do range.
#
# category_code:
#   administrados | livres | industriais | servicos | alim_domicilio

if (SKIP_PARETO_UPDATE) {
  cat("\n[8/9] SKIP_PARETO_UPDATE=1 — pulando merge (recon + pesos) em data/\n")
  quit(status = 0)
}

cat("\n[8] Atualizando base PARETO em ", PARETO_BASE_CSV, "...\n", sep = "")

periodo_to_date <- function(p) {
  as.Date(sprintf("%s-%s-01", substr(p, 1, 4), substr(p, 5, 6)))
}

stack_class <- function(cat_code, var_col) {
  data.frame(
    date          = periodo_to_date(out$periodo),
    category_code = cat_code,
    value         = out[[var_col]],
    stringsAsFactors = FALSE
  )
}

recon_long <- rbind(
  stack_class("total",          "ipca_oficial"),
  stack_class("administrados",  "var_admin"),
  stack_class("livres",         "var_livres"),
  stack_class("industriais",    "var_industr"),
  stack_class("servicos",       "var_serv"),
  stack_class("alim_domicilio", "var_alim_dom"),
  stack_class("nucleo_ex0",     "var_nucleo_ex0"),
  stack_class("nucleo_ex3",     "var_nucleo_ex3"),
  stack_class("duraveis",       "var_duravel"),
  stack_class("semiduraveis",   "var_semidur"),
  stack_class("ndur_industr",   "var_ndind"),
  stack_class("servicos_subj",  "var_serv_subj"),
  stack_class("servicos_exsubj","var_serv_exsubj"),
  stack_class("alim_in_natura", "var_alim_in"),
  stack_class("alim_semi_elab", "var_alim_se"),
  stack_class("alim_industr",   "var_alim_ind"),
  stack_class("comerc",         "var_comerc"),
  stack_class("ncomerc",        "var_ncomerc"),
  stack_class("nucleo_ma",      "var_nucleo_ma"),
  stack_class("nucleo_ms",      "var_nucleo_ms"),
  stack_class("nucleo_dp",      "var_nucleo_dp"),
  stack_class("nucleo_exfe",    "var_nucleo_exfe"),
  stack_class("nucleo_ex1",     "var_nucleo_ex1"),
  stack_class("ex3_serv",       "var_ex3_serv"),
  stack_class("ex3_ind",        "var_ex3_ind"),
  stack_class("difusao",        "var_difusao"),
  stack_class("nucleo_p55",     "var_nucleo_p55"),
  stack_class("nucleo_medio",   "var_nucleo_medio"),
  # Onda 6 — grupos IPCA + subgrupos/itens/subitens direto do IBGE
  stack_class("alim_e_bebidas",      "var_g1_alim_beb"),
  stack_class("habitacao",           "var_g2_habitacao"),
  stack_class("artigos_residencia",  "var_g3_artigos"),
  stack_class("vestuario",           "var_g4_vestuario"),
  stack_class("transportes",         "var_g5_transportes"),
  stack_class("despesas_pessoais",   "var_g7_desp_pess"),
  stack_class("educacao",            "var_g8_educacao"),
  stack_class("alim_fora",           "var_alim_fora"),
  stack_class("energia_eletrica",    "var_energia_el"),
  stack_class("passagem_aerea",      "var_passagem_aerea"),
  stack_class("auto_novo",           "var_auto_novo"),
  stack_class("auto_usado",          "var_auto_usado")
)
recon_long <- recon_long[!is.na(recon_long$value), ]

dir.create(dirname(PARETO_BASE_CSV), showWarnings = FALSE, recursive = TRUE)
if (file.exists(PARETO_BASE_CSV)) {
  existing <- read.csv(PARETO_BASE_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
  existing$date <- as.Date(existing$date)
  k_old <- paste(existing$date, existing$category_code)
  k_new <- paste(recon_long$date, recon_long$category_code)
  existing <- existing[!k_old %in% k_new, ]
  combined <- rbind(existing, recon_long)
} else {
  combined <- recon_long
}
combined <- combined[order(combined$date, combined$category_code), ]
write.csv(combined, PARETO_BASE_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("    OK. %d linhas (%s → %s) em %s\n",
            nrow(combined),
            format(min(combined$date)), format(max(combined$date)),
            PARETO_BASE_CSV))

# ---------------------------------------------------------------------------
# 9. Exporta pesos Laspeyres (data/ipca15_pareto_pesos.csv)
#
# Formato long: (date, category_code, value) com value = peso mensal agregado
# (Σ w_i dos subitens da classe, V66 SIDRA). Cobre as 21 categorias
# Laspeyres; as 6 restantes (MA/MS/DP/P55/difusao/nucleo_medio) não têm peso
# Laspeyres bem definido e ficam ausentes.

PARETO_PESOS_CSV <- Sys.getenv("PARETO_PESOS_CSV_OVR", unset = "data/ipca15_pareto_pesos.csv")
cat("\n[9] Atualizando pesos em ", PARETO_PESOS_CSV, "...\n", sep = "")
dir.create(dirname(PARETO_PESOS_CSV), showWarnings = FALSE, recursive = TRUE)

stack_peso <- function(cat_code, peso_col) {
  data.frame(
    date          = periodo_to_date(out$periodo),
    category_code = cat_code,
    value         = out[[peso_col]],
    stringsAsFactors = FALSE
  )
}

total_peso <- data.frame(
  date          = periodo_to_date(out$periodo),
  category_code = "total",
  value         = 100,
  stringsAsFactors = FALSE
)

pesos_long <- rbind(
  total_peso,
  stack_peso("administrados",   "peso_admin"),
  stack_peso("livres",          "peso_livres"),
  stack_peso("industriais",     "peso_industr"),
  stack_peso("servicos",        "peso_serv"),
  stack_peso("alim_domicilio",  "peso_alim_dom"),
  stack_peso("nucleo_ex0",      "peso_nucleo_ex0"),
  stack_peso("nucleo_ex3",      "peso_nucleo_ex3"),
  stack_peso("duraveis",        "peso_duravel"),
  stack_peso("semiduraveis",    "peso_semidur"),
  stack_peso("ndur_industr",    "peso_ndind"),
  stack_peso("servicos_subj",   "peso_serv_subj"),
  stack_peso("servicos_exsubj", "peso_serv_exsubj"),
  stack_peso("alim_in_natura",  "peso_alim_in"),
  stack_peso("alim_semi_elab",  "peso_alim_se"),
  stack_peso("alim_industr",    "peso_alim_ind"),
  stack_peso("comerc",          "peso_comerc"),
  stack_peso("ncomerc",         "peso_ncomerc"),
  stack_peso("nucleo_exfe",     "peso_nucleo_exfe"),
  stack_peso("nucleo_ex1",      "peso_nucleo_ex1"),
  stack_peso("ex3_serv",        "peso_ex3_serv"),
  stack_peso("ex3_ind",         "peso_ex3_ind"),
  # Onda 6 — pesos dos grupos/subgrupos/itens/subitens diretos do IBGE
  stack_peso("alim_e_bebidas",     "peso_g1_alim_beb"),
  stack_peso("habitacao",          "peso_g2_habitacao"),
  stack_peso("artigos_residencia", "peso_g3_artigos"),
  stack_peso("vestuario",          "peso_g4_vestuario"),
  stack_peso("transportes",        "peso_g5_transportes"),
  stack_peso("despesas_pessoais",  "peso_g7_desp_pess"),
  stack_peso("educacao",           "peso_g8_educacao"),
  stack_peso("alim_fora",          "peso_alim_fora"),
  stack_peso("energia_eletrica",   "peso_energia_el"),
  stack_peso("passagem_aerea",     "peso_passagem_aerea"),
  stack_peso("auto_novo",          "peso_auto_novo"),
  stack_peso("auto_usado",         "peso_auto_usado")
)
pesos_long <- pesos_long[!is.na(pesos_long$value), ]

if (file.exists(PARETO_PESOS_CSV)) {
  existing_p <- read.csv(PARETO_PESOS_CSV, stringsAsFactors = FALSE, encoding = "UTF-8")
  existing_p$date <- as.Date(existing_p$date)
  k_old_p <- paste(existing_p$date, existing_p$category_code)
  k_new_p <- paste(pesos_long$date, pesos_long$category_code)
  existing_p <- existing_p[!k_old_p %in% k_new_p, ]
  combined_p <- rbind(existing_p, pesos_long)
} else {
  combined_p <- pesos_long
}
combined_p <- combined_p[order(combined_p$date, combined_p$category_code), ]
write.csv(combined_p, PARETO_PESOS_CSV, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("    OK. %d linhas (%s → %s) em %s\n",
            nrow(combined_p),
            format(min(combined_p$date)), format(max(combined_p$date)),
            PARETO_PESOS_CSV))
