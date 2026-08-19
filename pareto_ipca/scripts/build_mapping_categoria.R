#!/usr/bin/env Rscript
# build_mapping_categoria.R
#
# Gera planilha long (category_code, cod_ibge, nome, nivel, peso_mm,
# tipo_mapping, fonte) mostrando quais subitens/itens do IBGE entram
# em cada uma das 44 categorias servidas pelo pipeline.
#
# Regras copiadas literalmente de reconstruct_ipca.R — se lá muda, aqui muda.
#
# Uso:
#   Rscript scripts/build_mapping_categoria.R              # último mês publicado
#   Rscript scripts/build_mapping_categoria.R 202606       # mês específico
#
# Saída: scripts/outputs/mapping_categoria_subitem.csv

suppressPackageStartupMessages({ library(httr); library(jsonlite) })

if (sys.nframe() == 0) {
  args0 <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args0, value = TRUE)
  if (length(file_arg)) {
    script_dir <- dirname(normalizePath(sub("^--file=", "", file_arg[1])))
    setwd(dirname(script_dir))
  }
}
if (file.exists("scripts/proxy_config.R")) source("scripts/proxy_config.R")

MASK_ADMIN_PATH <- "scripts/ipca_masks/administrados.csv"
MASK_CLASS_PATH <- Sys.getenv("MASK_CLASS_PATH_OVR",
                              unset = "scripts/ipca_masks/classificacao.csv")
OUT_DIR         <- Sys.getenv("OUT_DIR_OVR", unset = "scripts/outputs")
dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) >= 1L) {
  PERIODO <- as.integer(args[[1]])
} else {
  hoje <- Sys.Date()
  ref  <- seq(hoje, by = "-1 month", length.out = 3)
  PERIODO <- as.integer(format(ref[2], "%Y%m"))
}
cat(sprintf("[CFG] período de referência: %d\n", PERIODO))

# --- Regras hardcoded (idênticas a reconstruct_ipca.R) ---------------------

MS_ITEMS_SUAV <- c("2201","2202","5101","5104","7101","7202","8101","8104","9101")

EXFE_EXCL_SUBGRUPOS <- c("11","22")
EXFE_EXCL_SUBITENS  <- c("5102007")
EXFE_EXCL_ITENS     <- c("5104")
EXFE_KEEP_SUBITENS  <- c("1114003")

EX1_EXCL_ITENS <- c("1101","1103","1104","1105","1106","1107","1108","1110",
                    "1111","1113","2201","5104")

APARELHOS_ELETRO_PREFIX <- "32"
EX3_EXCL_CODES <- c("5102001","5102020","5104002","7202041")

COMERC_EXCL_NC_POF1718 <- c("1111004","1111008","1111011","1111019","1111021",
                            "1111031","1111038","1112015","1112017","1112019")
COMERC_INCL_C_ITEM_POF1718 <- "1106"

GRUPOS_DIRETOS <- list(
  alim_e_bebidas     = "1",
  habitacao          = "2",
  artigos_residencia = "3",
  vestuario          = "4",
  transportes        = "5",
  saude              = "6",
  despesas_pessoais  = "7",
  educacao           = "8",
  comunicacao        = "9",
  alim_fora          = "12",
  higiene_pessoal    = "63",
  energia_eletrica   = "2202",
  passagem_aerea     = "5101010",
  auto_novo          = "5102001",
  auto_usado         = "5102020",
  gasolina           = "5104001"
)

# --- Helpers SIDRA (mesmo padrão de reconstruct_ipca.R) --------------------

sidra_url <- function(agg, periodo, var) {
  sprintf(paste0("https://servicodados.ibge.gov.br/api/v3/agregados/%d/",
                 "periodos/%d/variaveis/%d?localidades=N1[all]&classificacao=315[all]"),
          agg, periodo, var)
}

fetch_sidra <- function(var_id, label, periodo) {
  url <- sidra_url(7060L, periodo, var_id)
  cat(sprintf("[GET] %s V%d ...\n", label, var_id))
  r <- GET(url, timeout(120))
  if (status_code(r) != 200)
    stop(sprintf("SIDRA V%d falhou: HTTP %d", var_id, status_code(r)))
  raw <- fromJSON(content(r, "text", encoding = "UTF-8"), simplifyDataFrame = FALSE)
  rows <- list()
  for (var_node in raw) for (res_node in var_node$resultados) {
    cls      <- res_node$classificacoes[[1]]
    cat_nome <- cls$categoria[[1]]
    for (s in res_node$series) {
      per_keys <- names(s$serie)
      per_vals <- as.character(unlist(s$serie))
      for (k in seq_along(per_keys)) {
        rows[[length(rows) + 1]] <- list(
          periodo = per_keys[k], cat_nome = cat_nome,
          valor = suppressWarnings(as.numeric(per_vals[k])))
      }
    }
  }
  do.call(rbind, lapply(rows, as.data.frame, stringsAsFactors = FALSE))
}

extrair_cod_ibge <- function(nome) {
  m <- regmatches(nome, regexpr("^[0-9]+", nome))
  ifelse(length(m) == 0, NA_character_, m)
}

# --- 1. Máscaras + fetch SIDRA --------------------------------------------

cat("\n[1] Carregando máscaras...\n")
mask_admin <- read.csv(MASK_ADMIN_PATH, stringsAsFactors = FALSE, encoding = "UTF-8")
mask_admin$cod_ibge <- as.character(mask_admin$cod_ibge)
mask_class <- read.csv(MASK_CLASS_PATH, stringsAsFactors = FALSE, encoding = "UTF-8")
mask_class$cod_ibge <- as.character(mask_class$cod_ibge)

cat(sprintf("\n[2] Fetch T7060 (%d)...\n", PERIODO))
df_var  <- fetch_sidra(63L, "variação", PERIODO)
df_peso <- fetch_sidra(66L, "peso",     PERIODO)
df_var$cod_ibge  <- sapply(df_var$cat_nome,  extrair_cod_ibge)
df_peso$cod_ibge <- sapply(df_peso$cat_nome, extrair_cod_ibge)

df <- merge(df_var[, c("cod_ibge", "cat_nome", "valor")],
            df_peso[, c("cod_ibge", "valor")],
            by = "cod_ibge", suffixes = c("_var","_peso"))
names(df)[names(df) == "valor_var"]  <- "var_mm"
names(df)[names(df) == "valor_peso"] <- "peso_mm"
df$nchar_cod <- nchar(df$cod_ibge)
df$nivel <- ifelse(is.na(df$cod_ibge), "geral",
              ifelse(df$nchar_cod == 7, "subitem",
                ifelse(df$nchar_cod == 4, "item",
                  ifelse(df$nchar_cod == 2, "subgrupo",
                    ifelse(df$nchar_cod == 1, "grupo", "outro")))))
df$is_admin <- !is.na(df$cod_ibge) & df$cod_ibge %in% mask_admin$cod_ibge
df <- merge(df, mask_class[, c("cod_ibge","classe","subjacente","proc_grau",
                                "bens_industriais")],
            by = "cod_ibge", all.x = TRUE)

subi <- df[df$nivel == "subitem", ]
itm  <- df[df$nivel == "item", ]
cat(sprintf("    universo: %d subitens, %d itens\n", nrow(subi), nrow(itm)))

# --- 2. Emissão long: (category_code, cod_ibge, nome, ...) -----------------

emit <- function(cat, sub_df, tipo, fonte) {
  if (!nrow(sub_df)) return(NULL)
  data.frame(
    category_code = cat,
    cod_ibge      = sub_df$cod_ibge,
    nome          = sub_df$cat_nome,
    nivel         = if ("nivel" %in% names(sub_df)) sub_df$nivel else "subitem",
    peso_mm       = sub_df$peso_mm,
    tipo_mapping  = tipo,
    fonte         = fonte,
    stringsAsFactors = FALSE
  )
}

emit_placeholder <- function(cat, tipo, fonte, universo_label = "TODO_UNIVERSO") {
  data.frame(
    category_code = cat,
    cod_ibge      = universo_label,
    nome          = universo_label,
    nivel         = "algoritmico",
    peso_mm       = NA_real_,
    tipo_mapping  = tipo,
    fonte         = fonte,
    stringsAsFactors = FALSE
  )
}

partes <- list()
add <- function(x) if (!is.null(x)) partes[[length(partes) + 1L]] <<- x

# 2a. Filtros na máscara (subitem-level) -----------------------------------
add(emit("total",           subi, "filtro", "universo IPCA"))
add(emit("administrados",   subi[subi$is_admin, ], "filtro",
         "administrados.csv"))
add(emit("livres",          subi[!subi$is_admin, ], "filtro",
         "!is_admin"))
add(emit("industriais",     subi[!is.na(subi$bens_industriais) & subi$bens_industriais, ],
         "filtro", "classificacao.csv: bens_industriais=TRUE"))
add(emit("duraveis",        subi[!is.na(subi$classe) & subi$classe == "duravel", ],
         "filtro", "classificacao.csv: classe=duravel"))
add(emit("semiduraveis",    subi[!is.na(subi$classe) & subi$classe == "semiduravel", ],
         "filtro", "classificacao.csv: classe=semiduravel"))
add(emit("ndur_industr",    subi[!is.na(subi$classe) & subi$classe == "nao_duravel_industrial", ],
         "filtro", "classificacao.csv: classe=nao_duravel_industrial"))
add(emit("servicos",        subi[!is.na(subi$classe) & subi$classe %in% c("servico","alimento_fora"), ],
         "filtro", "classificacao.csv: classe in {servico, alimento_fora}"))
add(emit("servicos_subj",   subi[!is.na(subi$classe) & subi$classe %in% c("servico","alimento_fora") &
                                 !is.na(subi$subjacente) & subi$subjacente, ],
         "filtro", "servicos + subjacente=TRUE (inclui alim_fora)"))
add(emit("servicos_exsubj", subi[!is.na(subi$classe) & subi$classe == "servico" &
                                 !is.na(subi$subjacente) & !subi$subjacente, ],
         "filtro", "classe=servico & subjacente=FALSE"))
add(emit("ex3_serv",        subi[!is.na(subi$classe) & subi$classe == "servico" &
                                 !is.na(subi$subjacente) & subi$subjacente, ],
         "filtro", "classe=servico & subjacente=TRUE (estrito, sem alim_fora)"))
add(emit("alim_domicilio",  subi[!is.na(subi$classe) & subi$classe == "alimento_domic", ],
         "filtro", "classificacao.csv: classe=alimento_domic"))
add(emit("alim_in_natura",  subi[!is.na(subi$proc_grau) & subi$proc_grau == "in_natura", ],
         "filtro", "classificacao.csv: proc_grau=in_natura"))
add(emit("alim_semi_elab",  subi[!is.na(subi$proc_grau) & subi$proc_grau == "semi_elab", ],
         "filtro", "classificacao.csv: proc_grau=semi_elab"))
add(emit("alim_industr",    subi[!is.na(subi$proc_grau) & subi$proc_grau == "industr", ],
         "filtro", "classificacao.csv: proc_grau=industr"))

# 2b. Núcleos por exclusão (subitem-level) ---------------------------------
add(emit("nucleo_ex0",
         subi[!subi$is_admin & (is.na(subi$classe) | subi$classe != "alimento_domic"), ],
         "exclusao", "NT_57 Sec 2.1.1: exclui admin + alim_dom"))

ex3_excl <- subi$is_admin |
            (!is.na(subi$classe) & subi$classe == "alimento_domic") |
            (!is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 2) == APARELHOS_ELETRO_PREFIX) |
            (!is.na(subi$cod_ibge) & subi$cod_ibge %in% EX3_EXCL_CODES) |
            (!is.na(subi$classe) & subi$classe == "servico" &
             !is.na(subi$subjacente) & !subi$subjacente)
add(emit("nucleo_ex3", subi[!ex3_excl, ],
         "exclusao", "NT_57 Sec 2.1.1: exclui admin+alim_dom+eletro(32)+5102001/020,5104002,7202041+serv_exsubj"))

exfe_excl <- (!is.na(subi$cod_ibge) &
              substr(subi$cod_ibge, 1, 2) %in% EXFE_EXCL_SUBGRUPOS &
              !subi$cod_ibge %in% EXFE_KEEP_SUBITENS) |
             (!is.na(subi$cod_ibge) & subi$cod_ibge %in% EXFE_EXCL_SUBITENS) |
             (!is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 4) %in% EXFE_EXCL_ITENS)
add(emit("nucleo_exfe", subi[!exfe_excl, ],
         "exclusao", "NT_57 Sec 2.1.1 (COICOP): exclui subgrupos 11+22, subitem 5102007, item 5104; keep 1114003"))

ex1_excl <- !is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 4) %in% EX1_EXCL_ITENS
add(emit("nucleo_ex1", subi[!ex1_excl, ],
         "exclusao", sprintf("NT_57 Sec 2.1.1: exclui 12 itens voláteis (%s)",
                             paste(EX1_EXCL_ITENS, collapse = ","))))

ex3_ind_excl <- (!is.na(subi$cod_ibge) & substr(subi$cod_ibge, 1, 2) == APARELHOS_ELETRO_PREFIX) |
                (!is.na(subi$cod_ibge) & subi$cod_ibge %in% EX3_EXCL_CODES)
add(emit("ex3_ind",
         subi[!is.na(subi$bens_industriais) & subi$bens_industriais & !ex3_ind_excl, ],
         "exclusao", "bens_industriais=TRUE & !eletro(32) & !EX3_EXCL_CODES"))

# 2c. Comercializáveis / Não-Comercializáveis -------------------------------
is_extended <- grepl("extended", MASK_CLASS_PATH, ignore.case = TRUE)
.comerc_excl      <- if (is_extended) character(0) else COMERC_EXCL_NC_POF1718
.comerc_incl_item <- COMERC_INCL_C_ITEM_POF1718

comerc_mask <-
  !subi$is_admin &
  !(!is.na(subi$cod_ibge) & subi$cod_ibge %in% .comerc_excl) &
  ((!is.na(subi$bens_industriais) & subi$bens_industriais) |
   (!is.na(subi$proc_grau) & subi$proc_grau %in% c("industr","semi_elab")) |
   (nzchar(.comerc_incl_item) & !is.na(subi$cod_ibge) &
    substr(subi$cod_ibge, 1, 4) == .comerc_incl_item))
add(emit("comerc", subi[comerc_mask, ], "regra_hibrida",
         "RI Dez/2019 Tab.5/6: !admin & (bens_ind OR proc in {industr,semi_elab} OR item=1106); exclui laticinios/panificados POF1718"))

ncomerc_mask <-
  !subi$is_admin &
  !(nzchar(.comerc_incl_item) & !is.na(subi$cod_ibge) &
    substr(subi$cod_ibge, 1, 4) == .comerc_incl_item) &
  ((!is.na(subi$classe) & subi$classe %in% c("servico","alimento_fora")) |
   (!is.na(subi$proc_grau) & subi$proc_grau == "in_natura") |
   (!is.na(subi$cod_ibge) & subi$cod_ibge %in% .comerc_excl))
add(emit("ncomerc", subi[ncomerc_mask, ], "regra_hibrida",
         "RI Dez/2019 Tab.5/6: !admin & (servicos+alim_fora OR proc=in_natura OR laticinios/panificados); frutas 1106→C"))

# 2d. Extraídos direto do SIDRA (agregados IBGE) ----------------------------
for (nm in names(GRUPOS_DIRETOS)) {
  cod <- GRUPOS_DIRETOS[[nm]]
  row_agg <- df[!is.na(df$cod_ibge) & df$cod_ibge == cod, ]
  add(emit(nm, row_agg, "sidra_direto",
           sprintf("SIDRA T7060 classificacao=315, cod=%s", cod)))
}

# 2e. Algorítmicos (universo aberto — sem lista fixa de subitens) -----------
add(emit_placeholder("nucleo_ma",
                     "algoritmico_item",
                     "trim 20/80 ponderado sobre TODOS os itens (nchar=4)",
                     universo_label = "TODOS_ITENS"))
add(emit_placeholder("nucleo_ms",
                     "algoritmico_item",
                     sprintf("igual MA + suavização geom 12m nos itens: %s",
                             paste(MS_ITEMS_SUAV, collapse = ",")),
                     universo_label = "TODOS_ITENS"))
add(emit_placeholder("nucleo_dp",
                     "algoritmico_item",
                     "sigma rolling 48m de (var_item - var_ipca); repondera por 1/sigma",
                     universo_label = "TODOS_ITENS"))
add(emit_placeholder("nucleo_p55",
                     "algoritmico_subitem",
                     "percentil 55 ponderado da distribuição cross-section",
                     universo_label = "TODOS_SUBITENS"))
add(emit_placeholder("difusao",
                     "algoritmico_subitem",
                     "% subitens com var>0 no mês",
                     universo_label = "TODOS_SUBITENS"))
add(emit_placeholder("nucleo_medio",
                     "meta",
                     "média(nucleo_ex0, nucleo_ex3, nucleo_ms, nucleo_dp, nucleo_p55)",
                     universo_label = "META_NUCLEOS"))

# --- 3. Consolida + escreve -----------------------------------------------

out <- do.call(rbind, partes)
out <- out[order(out$category_code, out$cod_ibge), ]

# Somatório de peso por categoria (sanity: bate com ipca_pareto_pesos.csv)
sum_peso <- aggregate(peso_mm ~ category_code, data = out, FUN = sum, na.rm = TRUE)
sum_n    <- aggregate(cod_ibge ~ category_code, data = out, FUN = length)
resumo   <- merge(sum_n, sum_peso, by = "category_code")
names(resumo) <- c("category_code", "n_componentes", "soma_peso_mm")
resumo$soma_peso_mm <- round(resumo$soma_peso_mm, 4)
resumo <- resumo[order(-resumo$soma_peso_mm), ]

out_path    <- file.path(OUT_DIR, "mapping_categoria_subitem.csv")
resumo_path <- file.path(OUT_DIR, "mapping_categoria_resumo.csv")
xlsx_path   <- file.path(OUT_DIR, "mapping_categoria_subitem.xlsx")

write.csv(out,    out_path,    row.names = FALSE, fileEncoding = "UTF-8")
write.csv(resumo, resumo_path, row.names = FALSE, fileEncoding = "UTF-8")

# Excel com AutoFilter + pane congelado. openxlsx grava UTF-8 nativamente
# (evita "GÃ¡s" que o Excel mostra ao abrir CSV UTF-8 sem BOM).
suppressPackageStartupMessages(library(openxlsx))
wb <- createWorkbook()
hdr <- createStyle(textDecoration = "bold", fgFill = "#D9E1F2",
                   border = "Bottom", halign = "left")
sec <- createStyle(textDecoration = "bold", fgFill = "#305496",
                   fontColour = "white", halign = "left")

# Manual: aba inaugural. Estrutura em seções (2 colunas: termo, explicação).
manual <- rbind(
  data.frame(termo = "HIERARQUIA IBGE (classificação 315)", explicacao = "",
             stringsAsFactors = FALSE),
  data.frame(termo = "grupo (nchar=1)",
             explicacao = "9 grupos top-level. Ex: 1=Alim. e bebidas, 2=Habitação, 5=Transportes, 9=Comunicação. cod_ibge de 1 dígito."),
  data.frame(termo = "subgrupo (nchar=2)",
             explicacao = "~24 subgrupos. Ex: 11=Alim. no domicílio, 12=Alim. fora, 22=Combustíveis e energia, 32=Aparelhos eletroeletrônicos, 63=Higiene pessoal."),
  data.frame(termo = "item (nchar=4)",
             explicacao = "51 itens. Ex: 1101=Cereais/leguminosas, 2201=Combust. domésticos, 2202=Energia elétrica, 5104=Combust. veículos. É o nível dos núcleos MA/MS/DP."),
  data.frame(termo = "subitem (nchar=7)",
             explicacao = "377 subitens. É o único nível com peso Laspeyres direto (V66). Ex: 1103028=Tomate, 5102001=Auto novo, 6203001=Plano de saúde."),
  data.frame(termo = "", explicacao = ""),

  data.frame(termo = "ABA `mapping` — COLUNAS", explicacao = ""),
  data.frame(termo = "category_code",
             explicacao = "Uma das 44 categorias servidas pelo pipeline (headline + 27 recon + 16 sidra_direto). Mesmos nomes que aparecem em ipca_pareto_pesos.csv."),
  data.frame(termo = "cod_ibge",
             explicacao = "Código IBGE do componente. Placeholder (TODOS_ITENS / TODOS_SUBITENS / META_NUCLEOS) pras categorias algorítmicas sem lista fixa."),
  data.frame(termo = "nome",
             explicacao = "Nome oficial IBGE (prefixado pelo cod_ibge). UTF-8."),
  data.frame(termo = "nivel",
             explicacao = "subitem | item | subgrupo | grupo | algoritmico. Segue nchar(cod_ibge)."),
  data.frame(termo = "peso_mm",
             explicacao = "Peso Laspeyres mensal (V66) do componente em pp do IPCA total. Muda mês a mês. Soma bate com Laspeyres agregado da categoria."),
  data.frame(termo = "tipo_mapping",
             explicacao = "Como a categoria é construída — ver seção `TIPOS DE MAPPING` abaixo."),
  data.frame(termo = "fonte",
             explicacao = "Descrição textual da regra ou origem do dado (arquivo de máscara, código SIDRA, seção da NT_57, etc.)."),
  data.frame(termo = "", explicacao = ""),

  data.frame(termo = "ABA `resumo` — COLUNAS", explicacao = ""),
  data.frame(termo = "category_code", explicacao = "Idem aba mapping."),
  data.frame(termo = "n_componentes",
             explicacao = "Quantos códigos IBGE compõem a categoria. `total` = 377 (universo subitens); grupos = 1 (agregado já publicado)."),
  data.frame(termo = "soma_peso_mm",
             explicacao = "Soma dos pesos dos componentes. Bate exato com ipca_pareto_pesos.csv pro mesmo mês (validado)."),
  data.frame(termo = "", explicacao = ""),

  data.frame(termo = "TIPOS DE MAPPING", explicacao = ""),
  data.frame(termo = "filtro",
             explicacao = "Seleção direta na máscara por coluna (classe / proc_grau / bens_industriais / is_admin). Ex: alim_in_natura = proc_grau=='in_natura'."),
  data.frame(termo = "exclusao",
             explicacao = "Universo total menos exclusões. Núcleos NT_57: EX0/EX3/EX-FE/EX1/ex3_ind. Lista de exclusão vem da NT_57 Sec 2.1.1."),
  data.frame(termo = "regra_hibrida",
             explicacao = "Combina filtros positivos + exclusões calibradas contra BCB SGS. Só comerc/ncomerc (frutas→C, laticínios/panificados→NC via RI Dez/2019 Tab.3)."),
  data.frame(termo = "sidra_direto",
             explicacao = "Agregado já publicado pelo IBGE (SIDRA classificacao=315), 1 cod_ibge por categoria. Nada é recomputado — só extraído. Ex: grupos G1-G9, alim_fora=12, energia_eletrica=2202, auto_novo=5102001."),
  data.frame(termo = "algoritmico_item",
             explicacao = "Sem lista fixa: aplica algoritmo estatístico sobre TODOS os 51 itens. MA (trim 20/80), MS (trim + suavização 12m em 9 itens), DP (repondera por 1/sigma rolling 48m)."),
  data.frame(termo = "algoritmico_subitem",
             explicacao = "Sem lista fixa: aplica algoritmo sobre TODOS os 377 subitens. P55 (percentil 55 ponderado), difusao (% subitens com var>0)."),
  data.frame(termo = "meta",
             explicacao = "Função de outras categorias. nucleo_medio = média(EX0, EX3, MS, DP, P55). Não tem peso próprio."),
  data.frame(termo = "", explicacao = ""),

  data.frame(termo = "NOTAS IMPORTANTES", explicacao = ""),
  data.frame(termo = "Por que só subitens têm peso?",
             explicacao = "IBGE publica pesos POF apenas no nível subitem (V66). Grupo/subgrupo/item são agregações de baixo pra cima. Por isso o Laspeyres opera em subitem."),
  data.frame(termo = "Por que soma bate 100?",
             explicacao = "Todo subitem pertence a exatamente 1 grupo/subgrupo/item, e a soma dos pesos POF é 100pp por construção. `total` = universo cheio = 100."),
  data.frame(termo = "Categorias sem peso Laspeyres",
             explicacao = "As 5 categorias algorítmicas (nucleo_ma/ms/dp/p55/difusao) e a meta (nucleo_medio) não têm peso agregado — não são recorte por peso, são resultado de operação estatística."),
  data.frame(termo = "Máscara: base vs extended",
             explicacao = "classificacao.csv = POF 2017-18 (377 subitens, usada pra 2020+). classificacao_extended.csv = 478 subitens cobrindo POFs anteriores (2002-03, 2008-09), usada só no seed histórico."),
  data.frame(termo = "Categorias vs SGS BCB",
             explicacao = "19 categorias têm série publicada pelo BCB (mean|d| 0.002-0.024pp). As demais (alim in_natura/se/ind, ndur_industr, serv_subj/exsubj, nucleo_medio) não têm SGS público — auditadas por consistência interna."),
  data.frame(termo = "Refresh do mapping",
             explicacao = "`Rscript scripts/build_mapping_categoria.R YYYYMM` regenera pra qualquer mês. Regras vêm de reconstruct_ipca.R (drift zero enquanto ninguém edita as regras).")
)

addWorksheet(wb, "manual")
writeData(wb, "manual", manual, headerStyle = hdr)
freezePane(wb, "manual", firstRow = TRUE)
setColWidths(wb, "manual", cols = 1:2, widths = c(38, 110))
# Realça linhas de seção (explicação vazia) com azul escuro.
sec_rows <- which(manual$explicacao == "") + 1L  # +1 pelo header
addStyle(wb, "manual", style = sec, rows = sec_rows, cols = 1:2,
         gridExpand = TRUE, stack = TRUE)

addWorksheet(wb, "mapping")
writeData(wb, "mapping", out, headerStyle = hdr, withFilter = TRUE)
freezePane(wb, "mapping", firstRow = TRUE)
setColWidths(wb, "mapping", cols = seq_len(ncol(out)),
             widths = c(20, 12, 42, 10, 10, 20, 60))

addWorksheet(wb, "resumo")
writeData(wb, "resumo", resumo, headerStyle = hdr, withFilter = TRUE)
freezePane(wb, "resumo", firstRow = TRUE)
setColWidths(wb, "resumo", cols = seq_len(ncol(resumo)), widths = c(22, 16, 16))

saveWorkbook(wb, xlsx_path, overwrite = TRUE)

cat(sprintf("\n[3] OK — %d linhas em %s\n", nrow(out), out_path))
cat(sprintf("        resumo (%d cats) em %s\n", nrow(resumo), resumo_path))
cat(sprintf("        xlsx (2 abas, filtros) em %s\n\n", xlsx_path))
print(resumo, row.names = FALSE)
