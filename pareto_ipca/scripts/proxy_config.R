# proxy_config.R — sourceado pelos scripts que fazem HTTP (seed/reconstruct).
# Edite os campos abaixo na máquina institucional. Sem este arquivo (ou com
# PROXY_HOST = "" abaixo), os scripts rodam SEM proxy — útil em casa.
#
# Como funciona:
#  - Sys.setenv() configura http_proxy/https_proxy pro curl (libcurl) inteiro
#  - httr::set_config(use_proxy(...)) força o httr a usar isso explicitamente
#  - Sem auth: deixe PROXY_USER / PROXY_PASS vazios
#  - Com auth básica: preencha USER/PASS (vai pra URL como user:pass@host:port)
#  - Auth NTLM/Kerberos integrada ao Windows: deixe vazio (sistema resolve)
#  - ssl_verifypeer = 0 só se proxy faz MITM e o cert corporativo não está no
#    bundle do curl. Comece com 1 (verifica); se der "SSL certificate problem",
#    aí muda pra 0.

PROXY_HOST <- ""          # ex.: "proxy.minhainstituicao.br"
PROXY_PORT <- ""          # ex.: "8080"
PROXY_USER <- ""          # vazio se não tiver auth básica
PROXY_PASS <- ""          # vazio se não tiver auth básica
SSL_VERIFY <- TRUE        # mude pra FALSE só se cert corporativo bloquear

# ---------------------------------------------------------------------------
# Não mexa daqui pra baixo.

if (nzchar(PROXY_HOST) && nzchar(PROXY_PORT)) {
  proxy_url <- if (nzchar(PROXY_USER)) {
    sprintf("http://%s:%s@%s:%s",
            utils::URLencode(PROXY_USER, reserved = TRUE),
            utils::URLencode(PROXY_PASS, reserved = TRUE),
            PROXY_HOST, PROXY_PORT)
  } else {
    sprintf("http://%s:%s", PROXY_HOST, PROXY_PORT)
  }
  Sys.setenv(http_proxy = proxy_url, https_proxy = proxy_url)
  if (requireNamespace("httr", quietly = TRUE)) {
    httr::set_config(httr::use_proxy(
      url      = PROXY_HOST,
      port     = as.integer(PROXY_PORT),
      username = if (nzchar(PROXY_USER)) PROXY_USER else NULL,
      password = if (nzchar(PROXY_PASS)) PROXY_PASS else NULL
    ), override = FALSE)
  }
  cat(sprintf("[PROXY] usando %s:%s%s\n",
              PROXY_HOST, PROXY_PORT,
              if (nzchar(PROXY_USER)) sprintf(" (user=%s)", PROXY_USER) else ""))
}

if (!isTRUE(SSL_VERIFY) && requireNamespace("httr", quietly = TRUE)) {
  httr::set_config(httr::config(ssl_verifypeer = 0L, ssl_verifyhost = 0L),
                   override = FALSE)
  cat("[PROXY] SSL verify DESABILITADO (cert corporativo). Use só em rede confiável.\n")
}
