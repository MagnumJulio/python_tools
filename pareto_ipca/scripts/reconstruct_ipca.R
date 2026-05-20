#!/usr/bin/env Rscript
# reconstruct_ipca.R
#
# Reconstrói as agregações BCB do IPCA (administrados, livres, industriais,
# serviços e alimentação no domicílio) a partir dos subitens publicados pelo
# IBGE em SIDRA T7060, usando as máscaras em scripts/ipca_masks/.
#
# Por que essa abordagem: IBGE não publica esses cortes em SIDRA — quem
# constrói é o BCB (SGS 4449/11428/27863/10844/27864). O BCB publica D+1 do
# IBGE. Reconstruir direto do IBGE entrega o número no mesmo dia do release.
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
#   scripts/outputs/ipca_validacao_bcb.csv    — comparação vs SGS 4449/11428/27863/10844/27864
#
# Uso:
#   cd backend
#   Rscript scripts/reconstruct_ipca.R              # roda últimos 24 meses
#   Rscript scripts/reconstruct_ipca.R 202401 202604  # janela específica

suppressPackageStartupMessages({
  library(httr)
  library(jsonlite)
})

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
                              unset = "data/ipca_pareto_recon.csv")
dir.create(dirname(PARETO_BASE_CSV), showWarnings = FALSE, recursive = TRUE)
SIDRA_AGG       <- as.integer(Sys.getenv("SIDRA_AGG_ID", unset = "7060"))
SKIP_PARETO_UPDATE <- nzchar(Sys.getenv("SKIP_PARETO_UPDATE", unset = ""))
SIDRA_VAR_VAR   <- 63L    # variação mensal
SIDRA_VAR_PESO  <- 66L    # peso mensal
SIDRA_CLS       <- 315L   # geral/grupos/subgrupos/itens/subitens
BCB_SGS_ADMIN   <- 4449L  # IPCA - Preços monitorados (variação mensal)
BCB_SGS_LIVRES  <- 11428L # IPCA - Itens livres (variação mensal)
BCB_SGS_INDUST  <- 27863L # IPCA - Industriais (variação mensal)
BCB_SGS_SERV    <- 10844L # IPCA - Serviços (variação mensal)
BCB_SGS_ALIM    <- 27864L # IPCA - Alimentos no domicílio (variação mensal)
BCB_SGS_NUC_EX0 <- 11427L # IPCA - Núcleo EX0 (sem monitorados e alim. domicílio)
BCB_SGS_NUC_EX3 <- 27839L # IPCA - Núcleo EX3
BCB_SGS_DUR     <- 10843L # IPCA - Bens duráveis
BCB_SGS_SEMIDUR <- 10842L # IPCA - Bens semi-duráveis
# OBS: SGS 1635/1636/1637 (alim in-nat/semi-el/industr BCB) e 10841 (bens não-dur
# BCB) existem na API mas não somam pra alim_dom (universo/pesos diferentes);
# expostos diretos via BCB/* — não validados aqui.
BCB_SGS_COMERC  <- 4447L  # IPCA - Comercializáveis (validado)
BCB_SGS_NCOMERC <- 4448L  # IPCA - Não-comercializáveis (validado)
# Onda 4 — Núcleos estatísticos BCB
BCB_SGS_NUC_MS  <- 4466L  # Núcleo MS (Médias Aparadas com Suavização)
BCB_SGS_NUC_MA  <- 11426L # Núcleo MA (Médias Aparadas sem Suavização)
BCB_SGS_NUC_DP  <- 16122L # Núcleo DP (Dupla Ponderação)
TOL_VALIDACAO   <- 0.05   # divergência aceitável em pp/mês na recomposição do IPCA

# Lista de subitens suavizados pelo BCB no MS (Figueiredo & Silva 2002,
# atualizada em Notas Técnicas BCB de 2014/2018). São itens com coleta
# anual ou reajuste concentrado em meses específicos — a média móvel 12m
# distribui o choque ao longo do ano antes da truncagem.
# Cobertura intencionalmente abrangente; itens não-presentes em T7060 são
# ignorados pelo subset (sem erro).
MS_SUAVIZADOS <- c(
  # Habitação — aluguel/condomínio/serviços de utilidade pública
  "3101001",  # Aluguel residencial
  "3101002",  # Condomínio
  "3201001",  # Taxa de água e esgoto
  "3201002",  # Taxa de água e esgoto - taxa
  "3301001",  # Energia elétrica residencial
  "3301002",  # Gás encanado / canalizado
  # Despesas pessoais — empregada doméstica
  "4501007",  # Empregado doméstico (mensalista)
  "4501009",  # Diarista
  # Saúde — planos
  "6201002", "6201013", "6201018",  # Plano de saúde (variantes históricas)
  # Educação — mensalidades escolares (todos os 8101*)
  "8101001", "8101002", "8101003", "8101004", "8101005",
  "8101006", "8101007", "8101008", "8101009", "8101010",
  "8101011", "8101012", "8101013",
  # Despesas pessoais — jogos/loterias
  "7401001", "7401002",
  # Tributos/taxas com reajuste anual
  "3102001",  # IPTU (admin)
  "5202005"   # IPVA (admin)
)

dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

# ---------------------------------------------------------------------------
# Janela de períodos (YYYYMM). Default: últimos 24 meses.

args <- commandArgs(trailingOnly = TRUE)
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

# Fetch helper com retry leve e parsing pra long format (periodo, cod_ibge, valor).
fetch_sidra <- function(var_id, label, periodo_str) {
  url <- sidra_url(SIDRA_AGG, periodo_str, var_id, SIDRA_CLS, NULL)
  cat(sprintf("[GET] %s V%d ...\n", label, var_id))
  r <- GET(url, timeout(120))
  if (status_code(r) != 200) {
    stop(sprintf("SIDRA V%d falhou: HTTP %d", var_id, status_code(r)))
  }
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
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
# Classificação heurística IBGE-item (regra tradicional, RI Mar/2014):
#   in_natura  = itens 1103/1105/1106/1108/1110 (+ alho 1116010)
#   semi_elab  = itens 1101/1107 (cereais/leguminosas + carnes cortes brutos)
#   industr    = itens 1102/1104/1109/1111/1112/1113/1114/1115/1116
#
# NÃO bate SGS BCB 1635/1636/1637 — esses usam definição/universo
# DIFERENTE (provavelmente IPA ou pesos POF antigos); a relação
# SGS_1635 + SGS_1636 + SGS_1637 ≠ SGS_27864 (alim. domicílio total).
# Como a soma das BCB não fecha em alim_dom, optamos por entregar
# nossa decomposição derivada do mesmo universo IBGE (subgrupo 11
# inteiro) — internamente consistente: var_alim_in*peso_alim_in +
# var_alim_se*peso_alim_se + var_alim_ind*peso_alim_ind, ponderado,
# recompõe var_alim_dom exatamente. A validação está em [5] como
# diff_alim_dom_recomp.
#
# Pra quem precisa da versão BCB-original, expor SGS 1635/1636/1637
# diretos via scripts/bcb_series.csv (BCB/IPCA_ALIM_IN_NATURA etc.).
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
# Definição BCB (clássica, RI/WP374):
#   COMERC   = bens industriais (D+SD+ND-ind) + alimentos industrializados
#              + alimentos semi-elaborados (cortes carne, cereais beneficiados)
#   NCOMERC  = serviços (incl. alim_fora) + monitorados + alim in-natura
#              (hortaliças, frutas, ovo, leite fresco — locais)
# Identidade: COMERC + NCOMERC = 100% peso. Valida vs SGS 4447 / 4448.
comerc_subi <- subi[
  (!is.na(subi$bens_industriais) & subi$bens_industriais) |
  (!is.na(subi$proc_grau) & subi$proc_grau %in% c("industr", "semi_elab")), ]
agg_comerc  <- calc_agg(comerc_subi)
names(agg_comerc)[2:3] <- c("var_comerc", "peso_comerc")

ncomerc_subi <- subi[
  subi$is_admin |
  (!is.na(subi$classe) & subi$classe %in% c("servico", "alimento_fora")) |
  (!is.na(subi$proc_grau) & subi$proc_grau == "in_natura"), ]
agg_ncomerc  <- calc_agg(ncomerc_subi)
names(agg_ncomerc)[2:3] <- c("var_ncomerc", "peso_ncomerc")

# Onda 4 — Núcleos estatísticos MS / MA / DP.
# Universo: TODOS os subitens (não exclui admin nem alimentos — o algoritmo
# estatístico já lida com outliers via truncagem ou re-pesagem por volatilidade).
# Pré-requisito: subi precisa estar ordenado por periodo + cod_ibge.

cat("\n[4b] Computando núcleos estatísticos MA/MS/DP por mês...\n")

periodos_ord <- sort(unique(subi$periodo))

# ---- MA: média truncada 20/80 sem suavização ----
agg_nucleo_ma <- data.frame(
  periodo = periodos_ord,
  var_nucleo_ma = sapply(periodos_ord, function(p) {
    x <- subi[subi$periodo == p, ]
    trimmed_mean(x$var_mm, x$peso_mm, lower = 0.20, upper = 0.80)
  }),
  stringsAsFactors = FALSE
)

# ---- MS: idem MA, mas pré-suaviza subitens MS_SUAVIZADOS via média móvel 12m ----
# Para cada subitem suavizado e cada período p, se houver 12 meses
# consecutivos {p-11..p} de var_mm disponíveis, substitui var_mm[p] pela
# média simples desses 12 meses. Senão, mantém o original.
subi_ms <- subi
subi_ms <- subi_ms[order(subi_ms$cod_ibge, subi_ms$periodo), ]
codes_suav <- intersect(MS_SUAVIZADOS, unique(subi_ms$cod_ibge))
cat(sprintf("    MS: %d / %d codes da lista oficial disponíveis em SIDRA\n",
            length(codes_suav), length(MS_SUAVIZADOS)))

for (cod in codes_suav) {
  idx <- which(subi_ms$cod_ibge == cod)
  if (length(idx) < 12) next
  v <- subi_ms$var_mm[idx]
  v_smooth <- rep(NA_real_, length(v))
  for (i in 12:length(v)) v_smooth[i] <- mean(v[(i-11):i], na.rm = TRUE)
  subi_ms$var_mm[idx] <- v_smooth
}

agg_nucleo_ms <- data.frame(
  periodo = periodos_ord,
  var_nucleo_ms = sapply(periodos_ord, function(p) {
    x <- subi_ms[subi_ms$periodo == p, ]
    trimmed_mean(x$var_mm, x$peso_mm, lower = 0.20, upper = 0.80)
  }),
  stringsAsFactors = FALSE
)

# ---- DP: dupla ponderação — peso final = peso_orig / sigma_i (vol histórica) ----
# Para cada subitem i, computa sigma_i = sd(var_mm[i, *]) sobre TODA a janela
# disponível (BCB usa janela longa de 5+ anos; com 76 meses 2020-2026 temos
# horizonte comparável). Janela única — não rolling — garante DP estável e
# previne dampening exagerado em períodos de alta inflação recente.
# Resultado: weighted_mean(var_mm[*,p], peso_mm[*,p] / sigma_i).
sigma_per_cod <- aggregate(
  var_mm ~ cod_ibge, data = subi,
  FUN = function(v) {
    v <- v[!is.na(v)]
    if (length(v) < 6) return(NA_real_)
    sd(v)
  }
)
names(sigma_per_cod)[2] <- "sigma"
subi_dp <- merge(subi, sigma_per_cod, by = "cod_ibge", all.x = TRUE)

agg_nucleo_dp <- data.frame(
  periodo = periodos_ord,
  var_nucleo_dp = sapply(periodos_ord, function(p) {
    x <- subi_dp[subi_dp$periodo == p, ]
    x <- x[!is.na(x$sigma) & x$sigma > 1e-6, ]
    if (!nrow(x)) return(NA_real_)
    wt <- x$peso_mm / x$sigma
    weighted_mean_simple(x$var_mm, wt)
  }),
  stringsAsFactors = FALSE
)

# Versão alternativa: livres via álgebra residual (controle de consistência)
out <- Reduce(function(a, b) merge(a, b, by = "periodo"),
              list(agg_admin, agg_livres, agg_industr, agg_serv, agg_alim_dom,
                   agg_nucleo_ex0, agg_nucleo_ex3,
                   agg_duravel, agg_semidur, agg_ndind,
                   agg_serv_subj, agg_serv_exsubj,
                   agg_alim_in, agg_alim_se, agg_alim_ind,
                   agg_comerc, agg_ncomerc,
                   agg_nucleo_ma, agg_nucleo_ms, agg_nucleo_dp,
                   ipca_geral))
out$var_livres_alg <- (out$ipca_oficial * (out$peso_admin + out$peso_livres) -
                       out$var_admin * out$peso_admin) / out$peso_livres
out$diff_livres_metodos <- out$var_livres - out$var_livres_alg

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
# 5. Validação contra BCB SGS

cat("\n[5] Validação contra BCB SGS...\n")
sgs_admin      <- fetch_bcb_sgs(BCB_SGS_ADMIN)
sgs_livres     <- fetch_bcb_sgs(BCB_SGS_LIVRES)
sgs_industr    <- fetch_bcb_sgs(BCB_SGS_INDUST)
sgs_serv       <- fetch_bcb_sgs(BCB_SGS_SERV)
sgs_alim_dom   <- fetch_bcb_sgs(BCB_SGS_ALIM)
sgs_nucleo_ex0 <- fetch_bcb_sgs(BCB_SGS_NUC_EX0)
sgs_nucleo_ex3 <- fetch_bcb_sgs(BCB_SGS_NUC_EX3)
sgs_duravel    <- fetch_bcb_sgs(BCB_SGS_DUR)
sgs_semidur    <- fetch_bcb_sgs(BCB_SGS_SEMIDUR)
sgs_comerc     <- fetch_bcb_sgs(BCB_SGS_COMERC)
sgs_ncomerc    <- fetch_bcb_sgs(BCB_SGS_NCOMERC)
sgs_nucleo_ma  <- fetch_bcb_sgs(BCB_SGS_NUC_MA)
sgs_nucleo_ms  <- fetch_bcb_sgs(BCB_SGS_NUC_MS)
sgs_nucleo_dp  <- fetch_bcb_sgs(BCB_SGS_NUC_DP)
# NOTA: SGS 1635/1636/1637 (alim in-nat/semi-el/industr BCB) e 10841
# (bens não-dur BCB) NÃO somam pra alim_dom — possivelmente usam pesos
# POF antigos ou universo diferente. Não usamos como validação direta.

names(sgs_admin)[2]      <- "bcb_admin"
names(sgs_livres)[2]     <- "bcb_livres"
names(sgs_industr)[2]    <- "bcb_industr"
names(sgs_serv)[2]       <- "bcb_serv"
names(sgs_alim_dom)[2]   <- "bcb_alim_dom"
names(sgs_nucleo_ex0)[2] <- "bcb_nucleo_ex0"
names(sgs_nucleo_ex3)[2] <- "bcb_nucleo_ex3"
names(sgs_duravel)[2]    <- "bcb_duravel"
names(sgs_semidur)[2]    <- "bcb_semidur"
names(sgs_comerc)[2]     <- "bcb_comerc"
names(sgs_ncomerc)[2]    <- "bcb_ncomerc"
names(sgs_nucleo_ma)[2]  <- "bcb_nucleo_ma"
names(sgs_nucleo_ms)[2]  <- "bcb_nucleo_ms"
names(sgs_nucleo_dp)[2]  <- "bcb_nucleo_dp"

val <- out[, c("periodo", "var_admin", "var_livres",
               "var_industr", "var_serv", "var_alim_dom",
               "var_nucleo_ex0", "var_nucleo_ex3",
               "var_duravel", "var_semidur", "var_ndind",
               "var_serv_subj", "var_serv_exsubj",
               "peso_serv_subj", "peso_serv_exsubj",
               "var_alim_in", "peso_alim_in",
               "var_alim_se", "peso_alim_se",
               "var_alim_ind", "peso_alim_ind",
               "peso_alim_dom",
               "var_comerc", "peso_comerc",
               "var_ncomerc", "peso_ncomerc",
               "var_nucleo_ma", "var_nucleo_ms", "var_nucleo_dp")]
val <- Reduce(function(a, b) merge(a, b, by = "periodo", all.x = TRUE),
              list(val, sgs_admin, sgs_livres, sgs_industr, sgs_serv,
                   sgs_alim_dom, sgs_nucleo_ex0, sgs_nucleo_ex3,
                   sgs_duravel, sgs_semidur, sgs_comerc, sgs_ncomerc,
                   sgs_nucleo_ma, sgs_nucleo_ms, sgs_nucleo_dp))
val$diff_admin      <- val$var_admin      - val$bcb_admin
val$diff_livres     <- val$var_livres     - val$bcb_livres
val$diff_industr    <- val$var_industr    - val$bcb_industr
val$diff_serv       <- val$var_serv       - val$bcb_serv
val$diff_alim_dom   <- val$var_alim_dom   - val$bcb_alim_dom
val$diff_nucleo_ex0 <- val$var_nucleo_ex0 - val$bcb_nucleo_ex0
val$diff_nucleo_ex3 <- val$var_nucleo_ex3 - val$bcb_nucleo_ex3
val$diff_duravel    <- val$var_duravel    - val$bcb_duravel
val$diff_semidur    <- val$var_semidur    - val$bcb_semidur
# Consistency: IN_NATURA + SEMI_ELAB + INDUSTR ponderado deve recompor ALIM_DOM.
val$var_alim_dom_recomp <- (val$var_alim_in  * val$peso_alim_in +
                            val$var_alim_se  * val$peso_alim_se +
                            val$var_alim_ind * val$peso_alim_ind) /
                           (val$peso_alim_in + val$peso_alim_se + val$peso_alim_ind)
val$diff_alim_dom_recomp <- val$var_alim_dom_recomp - val$var_alim_dom
val$diff_comerc     <- val$var_comerc     - val$bcb_comerc
val$diff_ncomerc    <- val$var_ncomerc    - val$bcb_ncomerc
val$diff_nucleo_ma  <- val$var_nucleo_ma  - val$bcb_nucleo_ma
val$diff_nucleo_ms  <- val$var_nucleo_ms  - val$bcb_nucleo_ms
val$diff_nucleo_dp  <- val$var_nucleo_dp  - val$bcb_nucleo_dp
# Identidade: peso_comerc + peso_ncomerc deve dar ~100
val$peso_comerc_total <- val$peso_comerc + val$peso_ncomerc
# Consistency: SUBJ + EXSUBJ ponderado deve recompor SERV total.
val$var_serv_recomp <- (val$var_serv_subj * val$peso_serv_subj +
                        val$var_serv_exsubj * val$peso_serv_exsubj) /
                       (val$peso_serv_subj + val$peso_serv_exsubj)
val$diff_serv_recomp <- val$var_serv_recomp - val$var_serv

cat("\n    Admin + Livres (pareto vs BCB):\n")
v1 <- val[, c("periodo", "var_admin", "bcb_admin", "diff_admin",
              "var_livres", "bcb_livres", "diff_livres")]
v1[, -1] <- lapply(v1[, -1], function(x) round(x, 4))
print(v1, row.names = FALSE)

cat("\n    Industriais + Serviços + Alim. domicílio (pareto vs BCB):\n")
v2 <- val[, c("periodo", "var_industr", "bcb_industr", "diff_industr",
              "var_serv", "bcb_serv", "diff_serv",
              "var_alim_dom", "bcb_alim_dom", "diff_alim_dom")]
v2[, -1] <- lapply(v2[, -1], function(x) round(x, 4))
print(v2, row.names = FALSE)

cat(sprintf("\n    erro absoluto médio admin:    %.4f pp\n",
            mean(abs(val$diff_admin),    na.rm = TRUE)))
cat(sprintf("    erro absoluto médio livres:   %.4f pp\n",
            mean(abs(val$diff_livres),   na.rm = TRUE)))
cat(sprintf("    erro absoluto médio industr:  %.4f pp\n",
            mean(abs(val$diff_industr),  na.rm = TRUE)))
cat(sprintf("    erro absoluto médio serviços: %.4f pp\n",
            mean(abs(val$diff_serv),     na.rm = TRUE)))
cat(sprintf("    erro absoluto médio alim_dom: %.4f pp\n",
            mean(abs(val$diff_alim_dom), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio núc.EX0:  %.4f pp\n",
            mean(abs(val$diff_nucleo_ex0), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio núc.EX3:  %.4f pp\n",
            mean(abs(val$diff_nucleo_ex3), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio duráveis:  %.4f pp\n",
            mean(abs(val$diff_duravel), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio semi-dur:  %.4f pp\n",
            mean(abs(val$diff_semidur), na.rm = TRUE)))
cat(sprintf("    consistência serv (SUBJ+EXSUBJ): %.4f pp\n",
            mean(abs(val$diff_serv_recomp), na.rm = TRUE)))
cat(sprintf("    consistência alim_dom (IN+SE+IND): %.4f pp\n",
            mean(abs(val$diff_alim_dom_recomp), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio comerc:    %.4f pp\n",
            mean(abs(val$diff_comerc), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio n-comerc:  %.4f pp\n",
            mean(abs(val$diff_ncomerc), na.rm = TRUE)))
cat(sprintf("    soma pesos (comerc+ncomerc): mín=%.2f máx=%.2f (esperado ~100)\n",
            min(val$peso_comerc_total, na.rm = TRUE),
            max(val$peso_comerc_total, na.rm = TRUE)))
cat(sprintf("    erro absoluto médio núc. MA:   %.4f pp\n",
            mean(abs(val$diff_nucleo_ma), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio núc. MS:   %.4f pp\n",
            mean(abs(val$diff_nucleo_ms), na.rm = TRUE)))
cat(sprintf("    erro absoluto médio núc. DP:   %.4f pp\n",
            mean(abs(val$diff_nucleo_dp), na.rm = TRUE)))

cat("\n    Núcleos estatísticos MA/MS/DP (pareto vs BCB):\n")
v8 <- val[, c("periodo", "var_nucleo_ma", "bcb_nucleo_ma", "diff_nucleo_ma",
              "var_nucleo_ms", "bcb_nucleo_ms", "diff_nucleo_ms",
              "var_nucleo_dp", "bcb_nucleo_dp", "diff_nucleo_dp")]
v8[, -1] <- lapply(v8[, -1], function(x) round(x, 4))
print(v8, row.names = FALSE)

cat("\n    Núcleos EX0 e EX3 (pareto vs BCB):\n")
v3 <- val[, c("periodo", "var_nucleo_ex0", "bcb_nucleo_ex0", "diff_nucleo_ex0",
              "var_nucleo_ex3", "bcb_nucleo_ex3", "diff_nucleo_ex3")]
v3[, -1] <- lapply(v3[, -1], function(x) round(x, 4))
print(v3, row.names = FALSE)

cat("\n    Bens duráveis e semi-duráveis (pareto vs BCB):\n")
v4 <- val[, c("periodo", "var_duravel", "bcb_duravel", "diff_duravel",
              "var_semidur", "bcb_semidur", "diff_semidur")]
v4[, -1] <- lapply(v4[, -1], function(x) round(x, 4))
print(v4, row.names = FALSE)

cat("\n    Serviços Subjacente / Ex-Subjacente (consistência):\n")
v5 <- val[, c("periodo", "var_serv_subj", "var_serv_exsubj",
              "var_serv_recomp", "var_serv", "diff_serv_recomp")]
v5[, -1] <- lapply(v5[, -1], function(x) round(x, 4))
print(v5, row.names = FALSE)

cat("\n    Alimentos in-natura/semi-elab/industr — heurística IBGE-item (consistência):\n")
v6 <- val[, c("periodo", "var_alim_in", "var_alim_se", "var_alim_ind",
              "var_alim_dom_recomp", "var_alim_dom", "diff_alim_dom_recomp")]
v6[, -1] <- lapply(v6[, -1], function(x) round(x, 4))
print(v6, row.names = FALSE)

cat("\n    Comercializáveis / Não-Comercializáveis (pareto vs BCB):\n")
v7 <- val[, c("periodo", "var_comerc", "bcb_comerc", "diff_comerc",
              "var_ncomerc", "bcb_ncomerc", "diff_ncomerc", "peso_comerc_total")]
v7[, -1] <- lapply(v7[, -1], function(x) round(x, 4))
print(v7, row.names = FALSE)

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
write.csv(val, file.path(OUT_DIR, "ipca_validacao_bcb.csv"),
          row.names = FALSE, fileEncoding = "UTF-8")
write.csv(aud, file.path(OUT_DIR, sprintf("ipca_auditoria_%s.csv", ultimo)),
          row.names = FALSE, fileEncoding = "UTF-8")
cat("    OK. Outputs em", OUT_DIR, "\n")

# ---------------------------------------------------------------------------
# 8. Atualiza a base servida via source=PARETO (data/ipca_pareto_recon.csv)
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
  cat("\n[8] SKIP_PARETO_UPDATE=1 — pulando merge em ", PARETO_BASE_CSV, "\n", sep = "")
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
  stack_class("nucleo_dp",      "var_nucleo_dp")
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
