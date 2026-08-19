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

# Manual: aba inaugural com texto longo/didático. 2 colunas (termo, explicacao).
# Linhas de seção têm explicação vazia — são realçadas como cabeçalho.
mkrow <- function(t, e = "") data.frame(termo = t, explicacao = e,
                                        stringsAsFactors = FALSE)
manual <- rbind(

  # === 1. O que é essa planilha =============================================
  mkrow("1. O QUE É ESSA PLANILHA"),
  mkrow("Objetivo",
        "Esta planilha responde a uma pergunta: QUAIS componentes do IPCA (subitens, itens, subgrupos ou grupos publicados pelo IBGE) entram em CADA UMA das 44 categorias analíticas de inflação que o pipeline pareto_ipca produz. É uma foto da composição, com pesos."),
  mkrow("Para quem serve",
        "Analistas que precisam auditar de onde vem o número de uma categoria (ex: 'quais 39 subitens compõem alim_in_natura?', 'qual o peso do tomate dentro do núcleo EX0?', 'quantos subitens sobrevivem à exclusão do EX1?'). Também serve pra explicar didática/metodologicamente o que cada agregado quer dizer."),
  mkrow("Estrutura do arquivo",
        "Três abas: (1) manual — este texto explicativo. (2) mapping — a planilha em si, 2 730 linhas long, uma linha por par (categoria, componente IBGE). (3) resumo — 38 categorias com contagem de componentes e peso agregado, útil pra ranking rápido."),
  mkrow("Como foi gerada",
        "Rodando o script scripts/build_mapping_categoria.R sobre os dados IBGE do mês de referência (T7060, V63+V66 via SIDRA). O script aplica as MESMAS regras usadas pelo pipeline de produção reconstruct_ipca.R — se lá muda, aqui muda também (drift zero por construção)."),
  mkrow(""),

  # === 2. Contexto ==========================================================
  mkrow("2. CONTEXTO — IPCA E AS AGREGAÇÕES DO BCB"),
  mkrow("O que é o IPCA",
        "Índice de Preços ao Consumidor Amplo. Calculado pelo IBGE mensalmente, é o índice OFICIAL de inflação do Brasil (usado pelo Copom nas metas de inflação). Mede a variação de preços de uma cesta ponderada de 377 subitens de bens e serviços consumidos por famílias com renda de 1 a 40 salários mínimos em 16 regiões metropolitanas. Os pesos vêm da POF (Pesquisa de Orçamentos Familiares) — atualmente POF 2017-18, vigente desde jan/2020."),
  mkrow("O que é uma 'categoria analítica' de inflação",
        "É um RECORTE do IPCA que ajuda a interpretar o movimento de preços por natureza econômica. Alguns exemplos didáticos: 'serviços' isola inflação de aluguel/plano de saúde/mensalidades escolares (é a parte persistente, ligada a salários e demanda doméstica); 'administrados' isola tarifas de eletricidade/água/combustível (preço regulado, choque exógeno de política pública ou câmbio); 'núcleos' tentam capturar inflação de TENDÊNCIA filtrando ruído/volatilidade (excluindo alimentos in-natura, combustíveis, etc.). O Copom acompanha esse conjunto no Relatório de Política Monetária."),
  mkrow("Por que o pipeline reconstrói tudo do IBGE",
        "Porque o BCB publica essas séries em D+1 do release IBGE (via SGS). Reconstruindo do detalhe IBGE (nível subitem), o pareto_ipca entrega os mesmos números no MESMO DIA do release IBGE — ganha 1 dia útil. A metodologia é fiel à NT_57/Dez-2025 do BCB (nota consolidada mais recente sobre núcleos)."),
  mkrow(""),

  # === 3. Hierarquia IBGE ===================================================
  mkrow("3. HIERARQUIA IBGE (CLASSIFICAÇÃO 315)"),
  mkrow("Ideia geral",
        "O IPCA é HIERÁRQUICO. Do topo pra base: 9 GRUPOS → 24 SUBGRUPOS → 51 ITENS → 377 SUBITENS. Todo subitem pertence a exatamente 1 item, 1 subgrupo e 1 grupo — não há sobreposição. O código IBGE (cod_ibge) reflete essa hierarquia: o COMPRIMENTO do código diz o nível, e cada nível prefixa os níveis abaixo."),
  mkrow("grupo (nchar=1) — 9 códigos",
        "Categorias top-level do IPCA. Códigos '1' a '9': 1=Alimentação e bebidas, 2=Habitação, 3=Artigos de residência, 4=Vestuário, 5=Transportes, 6=Saúde e cuidados pessoais, 7=Despesas pessoais, 8=Educação, 9=Comunicação. Cada grupo é a raiz de uma sub-árvore."),
  mkrow("subgrupo (nchar=2) — ~24 códigos",
        "Recorte intermediário. Os 2 dígitos começam com o dígito do grupo pai. Ex: '11'=Alimentação no domicílio (pai=grupo 1), '12'=Alimentação fora (pai=grupo 1), '22'=Combustíveis e energia (pai=grupo 2 Habitação), '32'=Aparelhos eletroeletrônicos (pai=grupo 3), '63'=Higiene pessoal (pai=grupo 6)."),
  mkrow("item (nchar=4) — 51 códigos",
        "Categorias médias, agrupam subitens 'do mesmo tipo'. Prefixo = subgrupo. Ex: '1101'=Cereais/leguminosas/oleaginosas (sub 11), '1103'=Tubérculos/raízes/legumes, '1106'=Frutas, '1107'=Carnes, '2201'=Combustíveis domésticos (gás GLP/encanado), '2202'=Energia elétrica residencial, '5104'=Combustíveis para veículos, '8101'=Cursos regulares. É o NÍVEL EM QUE OS NÚCLEOS MA/MS/DP OPERAM (trim é feito ordenando os 51 itens por variação)."),
  mkrow("subitem (nchar=7) — 377 códigos",
        "Nível MAIS granular do IPCA. É o único nível com PESO LASPEYRES DIRETO (V66 na SIDRA). TODAS as agregações Laspeyres (grupos/subgrupos/itens/categorias analíticas) são somas ponderadas de subitens. Prefixo = item. Ex: '1103028'=Tomate (item 1103), '1106017'=Maçã (item 1106), '5102001'=Automóvel novo (item 5102), '5104001'=Gasolina (item 5104), '5104002'=Etanol, '6203001'=Plano de saúde, '8101001'=Ensino fundamental."),
  mkrow("Como saber o nível de um cod_ibge",
        "Basta contar os dígitos. A coluna 'nivel' da aba mapping já faz isso pra você: nchar=1 → grupo, nchar=2 → subgrupo, nchar=4 → item, nchar=7 → subitem. Para as categorias algorítmicas (que não têm lista fixa) o nível vira 'algoritmico'."),
  mkrow(""),

  # === 4. Peso Laspeyres ====================================================
  mkrow("4. O QUE É PESO LASPEYRES"),
  mkrow("Definição",
        "Peso Laspeyres = parcela do gasto de uma família típica que vai pra cada subitem, medida pela POF. Ex: peso do subitem 'Tomate' = 0.35 significa que 0.35% do orçamento familiar médio (nas 16 regiões metropolitanas) é gasto com tomate. A soma dos pesos de todos os 377 subitens é 100% por construção."),
  mkrow("Por que 'mensal' (coluna peso_mm)",
        "Os pesos POF são fixados pela pesquisa base (POF 2017-18 desde jan/2020), MAS o IBGE renormaliza mensalmente para cobrir substituições de produtos e ajustes técnicos (subitens inseridos/retirados da coleta). Por isso peso_mm (variável V66 da SIDRA) muda pouco de mês a mês, mas muda."),
  mkrow("Como o peso agrega",
        "Peso de uma categoria = SOMA dos pesos dos subitens que a compõem. Ex: peso_alim_domicilio (15.6943 em Jun/2026) = soma dos peso_mm dos 159 subitens da classe alimento_domic. Peso do grupo Transportes (20.27) = soma dos pesos de todos os subitens que começam com '5'."),
  mkrow("Por que a soma da planilha bate com ipca_pareto_pesos.csv",
        "Porque a lógica é IDÊNTICA à do pipeline. A planilha aplica as mesmas regras que reconstruct_ipca.R usa pra gerar o CSV de pesos servido no SQL corp. Validado nas 38 categorias com peso Laspeyres bem definido: bateu 100% exato em Jun/2026."),
  mkrow(""),

  # === 5. Aba mapping — colunas =============================================
  mkrow("5. ABA `mapping` — EXPLICAÇÃO DE CADA COLUNA"),
  mkrow("category_code",
        "Nome curto da categoria analítica. Uma das 44 servidas pelo pipeline: total (IPCA cheio), administrados, livres, industriais, servicos, alim_domicilio, alim_in_natura, alim_semi_elab, alim_industr, nucleo_ex0, nucleo_ex3, nucleo_ex1, nucleo_exfe, nucleo_ma, nucleo_ms, nucleo_dp, nucleo_p55, nucleo_medio, difusao, comerc, ncomerc, servicos_subj, servicos_exsubj, ex3_serv, ex3_ind, alim_e_bebidas (=grupo 1), habitacao (=grupo 2), ..., alim_fora (=subgrupo 12), higiene_pessoal (=subgrupo 63), energia_eletrica (=item 2202), passagem_aerea, auto_novo, auto_usado, gasolina. São os mesmos nomes que aparecem em data/ipca_pareto_pesos.csv e data/ipca_pareto_recon.csv."),
  mkrow("cod_ibge",
        "Código IBGE do COMPONENTE (não da categoria). Uma linha da planilha representa 1 par (categoria, componente). Ex: linha (alim_in_natura, 1103028) diz 'o subitem 1103028 Tomate entra na categoria alim_in_natura'. Pras 6 categorias algorítmicas que operam sobre TODO o universo sem lista fixa, o cod_ibge vira placeholder: TODOS_ITENS (para MA/MS/DP), TODOS_SUBITENS (para P55/difusao) ou META_NUCLEOS (para nucleo_medio)."),
  mkrow("nome",
        "Nome oficial IBGE do componente, prefixado pelo cod_ibge. UTF-8 nativo (acentos corretos). Ex: '1103028.Tomate', '5102001.Automóvel novo', '6203001.Plano de saúde', '1114003.Bebidas alcoólicas'. Pras categorias sidra_direto (grupos/subgrupos), fica só o nome do agregado publicado pelo IBGE (ex: 'Alimentação e bebidas')."),
  mkrow("nivel",
        "Nível hierárquico do componente. Valores possíveis: subitem, item, subgrupo, grupo, algoritmico. Determinado por nchar(cod_ibge). 99% das linhas são 'subitem' — só as 16 categorias sidra_direto podem ter outros níveis (a maioria delas usa grupo ou subgrupo agregado)."),
  mkrow("peso_mm",
        "Peso Laspeyres MENSAL desse componente em pontos percentuais (pp) do IPCA total, para o mês de referência da planilha. Ex: peso_mm=4.1138 na linha (energia_eletrica, 2202003) significa 'o subitem 2202003 Energia elétrica residencial pesa 4.11% do IPCA em Jun/2026'. Pras categorias algorítmicas fica NA — não há peso Laspeyres bem definido pra elas."),
  mkrow("tipo_mapping",
        "Descreve COMO A REGRA DA CATEGORIA FOI CONSTRUÍDA. ATENÇÃO: não descreve o componente individual da linha, descreve a NATUREZA da regra da categoria toda. Ver seção 7 abaixo — é a parte mais sujeita a erro de interpretação."),
  mkrow("fonte",
        "Descrição textual da regra ou origem do dado. Serve pra rastreabilidade — dá pra ir direto olhar a máscara ou a seção da nota técnica citada. Exemplos: 'classificacao.csv: proc_grau=in_natura', 'NT_57 Sec 2.1.1: exclui admin + alim_dom', 'SIDRA T7060 classificacao=315, cod=5102001', 'trim 20/80 ponderado sobre TODOS os itens (nchar=4)'."),
  mkrow(""),

  # === 6. Aba resumo — colunas ==============================================
  mkrow("6. ABA `resumo` — EXPLICAÇÃO DE CADA COLUNA"),
  mkrow("category_code",
        "Idêntico à coluna homônima da aba mapping."),
  mkrow("n_componentes",
        "Quantidade de linhas que aquela categoria tem na aba mapping — o TAMANHO da agregação. Ex: total = 377 (universo cheio de subitens); nucleo_ex1 = 264 (excluídos 12 itens voláteis dos 51 possíveis); alim_e_bebidas = 1 (agregado já publicado pelo IBGE, uma única linha SIDRA)."),
  mkrow("soma_peso_mm",
        "Soma dos peso_mm dos componentes daquela categoria — o PESO AGREGADO da categoria em pp do IPCA. Ex: soma_peso_mm(administrados) = 26.13pp significa que preços administrados representam 26.13% do IPCA em Jun/2026. Pra categorias algorítmicas fica em branco (NA)."),
  mkrow(""),

  # === 7. tipo_mapping — armadilha ==========================================
  mkrow("7. tipo_mapping — ATENÇÃO À ARMADILHA INTERPRETATIVA"),
  mkrow("Regra de ouro",
        "TODA linha da planilha é um componente INCLUÍDO na categoria daquela linha. Sempre. Sem exceção. Se um subitem NÃO faz parte da categoria X, ele SIMPLESMENTE NÃO APARECE nas linhas de category_code=X. Não existe 'linha marcada como excluída' — o que ficou de fora não está na planilha."),
  mkrow("Erro comum a evitar",
        "Ler 'Ferragens' numa linha com category_code=ex3_ind e tipo_mapping=exclusao e concluir que ferragens foi EXCLUÍDA de ex3_ind. Errado. O que a linha diz é: (1) a categoria ex3_ind é DEFINIDA por exclusão (parte do universo de bens_industriais e remove uma lista de exceções — eletroeletrônicos, auto novo/usado, etanol, cigarro); (2) ferragens SOBREVIVEU à lista de exclusão, portanto ESTÁ INCLUÍDA em ex3_ind. Se ferragens estivesse fora, ela simplesmente não estaria em nenhuma linha de ex3_ind."),
  mkrow("Como descobrir o que ficou DE FORA",
        "Se você quer ver o que foi EXCLUÍDO de uma categoria por exclusão (ex: ex3_ind), compare com o universo pai. Filtre category_code=industriais (universo de bens industriais) e category_code=ex3_ind, e faça a diferença de cod_ibge — o que está em industriais mas não em ex3_ind é a lista de exclusão."),
  mkrow("tipo_mapping = filtro",
        "REGRA POSITIVA: 'inclua todo componente que satisfaz condição X'. Exemplos: alim_in_natura filtra proc_grau=='in_natura' na máscara → 39 subitens. servicos filtra classe in {servico, alimento_fora} → 68 subitens. duraveis filtra classe=='duravel' → 25 subitens. Se um subitem satisfaz a condição, entra; se não, fica de fora."),
  mkrow("tipo_mapping = exclusao",
        "REGRA COMPLEMENTAR: 'pega o universo total (ou um subconjunto amplo) e REMOVE uma lista específica'. Os 5 núcleos por exclusão são assim (NT_57 Sec 2.1.1): EX0 = todo IPCA menos {admin, alim_dom} → 181 subitens; EX3 = idem menos {eletroeletrônicos subgrupo 32, auto novo/usado, etanol, cigarro, serviços exsubjacentes} → 144; EX-FE (COICOP) = todo IPCA menos {alim_dom exceto bebida alcoólica, combustíveis+energia subgrupo 22, óleo lubrificante, combustíveis veículos item 5104} → 210; EX1 = todo IPCA menos 12 itens voláteis (alimentos sazonais + combustíveis) → 264; ex3_ind = bens_industriais menos {eletroeletrônicos, auto novo/usado, etanol, cigarro} → 99."),
  mkrow("tipo_mapping = regra_hibrida",
        "COMBINA INCLUSÕES POSITIVAS + EXCLUSÕES ESPECÍFICAS, geralmente calibrada empiricamente contra SGS BCB. Só comerc/ncomerc usam isso. Ex: comerc = !admin & (bens_industriais OU proc_grau in {industr, semi_elab} OU item=1106 frutas) MENOS a lista de laticínios/panificados reclassificados na POF 2017-18. As exceções vêm da RI Dez/2019 Tab.3 — o BCB reclassificou laticínios/panificados de Comercializáveis→Não-Comercializáveis e frutas de NC→C na migração POF 2008-09→2017-18."),
  mkrow("tipo_mapping = sidra_direto",
        "CATEGORIA JÁ VEM PRONTA DO IBGE — ZERO recomputação. IBGE publica esses agregados via SIDRA classificacao=315, basta EXTRAIR o cod_ibge correspondente. 16 categorias do pipeline são assim: os 9 grupos (alim_e_bebidas=1, habitacao=2, ..., comunicacao=9), 2 subgrupos (alim_fora=12, higiene_pessoal=63), 1 item (energia_eletrica=2202), 4 subitens (passagem_aerea=5101010, auto_novo=5102001, auto_usado=5102020, gasolina=5104001). Cada uma tem UMA ÚNICA LINHA na aba mapping — o campo 'nivel' reflete o nível do agregado publicado."),
  mkrow("tipo_mapping = algoritmico_item",
        "SEM LISTA FIXA de subitens. Aplica algoritmo estatístico sobre TODOS os 51 itens (nchar=4). Nenhum item é 'excluído a priori' — o algoritmo decide mês a mês qual entra no cálculo. Três variantes: MA (Médias Aparadas) = ordena os 51 itens por variação mensal, tira 20% de peso em cada cauda, calcula média ponderada dos 60% centrais. MS (MA Suavizadas) = idem, mas antes suaviza 9 itens listados na NT_57 Tab.5 (Combustíveis dom/veic, Energia elétrica, Transporte público, Serviços pessoais, Fumo, Cursos regulares/diversos, Comunicação) pela média geométrica dos últimos 12 meses. DP (Dupla Ponderação) = repondera cada item por 1/sigma_k, onde sigma_k é o desvio-padrão rolling 48m da diferença (var_item − var_ipca_cheio). Por isso a planilha usa placeholder TODOS_ITENS."),
  mkrow("tipo_mapping = algoritmico_subitem",
        "SEM LISTA FIXA. Aplica algoritmo sobre TODOS os 377 subitens. Duas variantes: P55 (Percentil 55 ponderado) = ordena os 377 subitens por variação, encontra o primeiro subitem cujo peso acumulado atinge 55%, retorna a variação DELE (mês a mês é UM subitem diferente). Difusão = conta a % de subitens (sem ponderação) com variação positiva no mês. Placeholder TODOS_SUBITENS."),
  mkrow("tipo_mapping = meta",
        "CATEGORIA QUE É FUNÇÃO DE OUTRAS CATEGORIAS. Só o nucleo_medio é assim: média aritmética simples das variações dos 5 núcleos do conjunto novo BCB (EX0, EX3, MS, DP, P55). É uma referência primária que o Copom acompanha no Relatório de Política Monetária. Placeholder META_NUCLEOS."),
  mkrow(""),

  # === 8. Notas importantes =================================================
  mkrow("8. NOTAS IMPORTANTES / FAQ"),
  mkrow("Por que só subitens têm peso individual",
        "A POF publica pesos apenas no nível SUBITEM (variável V66 no IBGE). Item/subgrupo/grupo são agregações de baixo pra cima — o peso deles é derivado (soma dos subitens filhos). Por isso o Laspeyres opera em subitem: é o único nível com peso 'de origem'."),
  mkrow("Por que a soma dos pesos bate 100",
        "Todo subitem pertence a EXATAMENTE 1 grupo, 1 subgrupo e 1 item (hierarquia disjunta, sem sobreposição). A soma dos pesos POF de todos os 377 subitens é 100pp por construção da pesquisa. Consequência: peso_g1 + peso_g2 + ... + peso_g9 = 100. E peso_alim_domicilio + peso_alim_fora + peso_administrados + peso_(demais_servicos) + peso_industriais = 100."),
  mkrow("Categorias sem peso Laspeyres agregado",
        "As 6 categorias algorítmicas (nucleo_ma, nucleo_ms, nucleo_dp, nucleo_p55, difusao, nucleo_medio) não têm peso agregado porque não são recorte por peso — são resultado de operação estatística sobre o universo. Ex: pra P55 não faz sentido perguntar 'qual o peso do P55?' — em cada mês, P55 é a variação de UM subitem específico (aquele em que o peso acumulado bate 55%), e esse subitem MUDA de mês pra mês."),
  mkrow("Um subitem pode aparecer em várias categorias",
        "Sim, e é o caso mais comum. A planilha tem 2 730 linhas mas o universo tem só 377 subitens únicos — cada subitem aparece em ~7 categorias em média. Exemplo típico: '6203001.Plano de saúde' entra em: total, livres, servicos, servicos_subj, ex3_serv, nucleo_ex0, nucleo_ex3, nucleo_exfe, nucleo_ex1, ncomerc. Grupo 6 (saúde) aparece só como sidra_direto agregado — o subitem em si só aparece nas categorias definidas por regra."),
  mkrow("Máscara base vs extended",
        "Esta planilha usa classificacao.csv (máscara BASE, POF 2017-18, 377 subitens) — a que serve pra período 2020+. Existe também classificacao_extended.csv (478 subitens, cobre POFs anteriores 2002-03 e 2008-09), usada só no seed histórico (tabelas SIDRA T2938 + T1419). Se rodar o script apontando MASK_CLASS_PATH_OVR pra máscara extended, algumas categorias mudam ligeiramente de composição (aparecem subitens extintos: feijão branco, chuchu, cinema, etc.)."),
  mkrow("Categorias com SGS BCB vs sem",
        "Das 27 categorias reconstruídas, 19 têm série publicada pelo BCB (SGS) e são auditadas com mean|d| < 0.025pp — bate quase exato. Não têm SGS público: alim_in_natura, alim_semi_elab, alim_industr, ndur_industr, ex3_serv (versão estrita sem alim_fora), nucleo_medio. Estas são auditadas por CONSISTÊNCIA INTERNA — ex: alim_in + alim_se + alim_ind ponderado tem que dar alim_dom."),
  mkrow("Refresh do mapping pra outro mês",
        "Rscript scripts/build_mapping_categoria.R YYYYMM regenera a planilha pra qualquer mês publicado. Ex: 'Rscript scripts/build_mapping_categoria.R 202507' gera pra Jul/2025. Sem argumento, usa o último mês publicado (mês passado). A COMPOSIÇÃO (quem entra em cada categoria) é essencialmente estável dentro de uma POF — só os pesos mudam mês a mês."),
  mkrow("Fonte da metodologia",
        "Fonte primária: BCB Nota Técnica NT_57 (Dez/2025) — 'Núcleos de inflação, séries por exclusão e outras agregações analíticas do IPCA'. É a nota consolidada mais recente do BC. Regras específicas de classificação (classe=alimento_domic/servico/duravel/etc.) vêm da RI Dez/2019 Tab.5. Reclassificações C↔NC na migração POF vêm da RI Dez/2019 Tab.3. Núcleo P55 (do conjunto novo BCB) vem do estudo EE102/2021 do próprio BC."),
  mkrow("Onde ver os arquivos-fonte",
        "Máscaras: pareto_ipca/scripts/ipca_masks/{classificacao.csv, classificacao_extended.csv, administrados.csv}. Regras algorítmicas: pareto_ipca/scripts/reconstruct_ipca.R (linhas 100-175 têm as listas hardcoded EX-FE/EX1/MS/reclassificações C↔NC; linhas 466-780 têm as filtragens por categoria). Notas técnicas: pareto_ipca/NT_57_202512.pdf, EE102_*.pdf, ri201912b7p.pdf.")
)

addWorksheet(wb, "manual")
writeData(wb, "manual", manual, headerStyle = hdr)
freezePane(wb, "manual", firstRow = TRUE)
setColWidths(wb, "manual", cols = 1:2, widths = c(38, 130))

# wrapText na coluna de explicação (pra Excel quebrar linha automaticamente).
wrap_style <- createStyle(wrapText = TRUE, valign = "top")
addStyle(wb, "manual", style = wrap_style,
         rows = seq_len(nrow(manual)) + 1L, cols = 2,
         gridExpand = TRUE, stack = TRUE)

# Realça linhas de seção (explicação vazia) com azul escuro.
sec_rows <- which(manual$explicacao == "") + 1L  # +1 pelo header
addStyle(wb, "manual", style = sec, rows = sec_rows, cols = 1:2,
         gridExpand = TRUE, stack = TRUE)

# Altura de linha adaptada ao tamanho do texto (≈ 15pt por linha lógica,
# considerando ~155 chars por linha na coluna B com width=130).
row_heights <- sapply(manual$explicacao, function(x) {
  if (!nzchar(x)) return(24)  # seção
  n_lines <- max(1L, ceiling(nchar(x) / 145))
  min(300, 15 * n_lines + 8)
})
setRowHeights(wb, "manual", rows = seq_len(nrow(manual)) + 1L,
              heights = row_heights)

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
