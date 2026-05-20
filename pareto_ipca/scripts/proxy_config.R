# proxy_config.R — sourceado pelos scripts que fazem HTTP (seed/reconstruct).
# Edite os campos abaixo na máquina institucional. Sem este arquivo (ou com
# PROXY_HOST = "" abaixo), os scripts rodam SEM proxy — útil em casa.
#
# Caso comum (mesmo proxy pra HTTP e HTTPS, sem auth):
#   preenche PROXY_HOST + PROXY_PORT e pronto.
#
# Casos especiais:
#   - Hosts/portas DIFERENTES pra HTTP e HTTPS: preencha HTTPS_PROXY_HOST/PORT.
#     Senão deixa vazio que herda de PROXY_HOST/PORT.
#   - Canal até o proxy é TLS (raro): mude HTTPS_PROXY_SCHEME pra "https".
#   - Auth básica (user/senha no proxy): preenche PROXY_USER/PASS.
#   - Auth NTLM/Kerberos integrada ao Windows: deixa USER/PASS vazios; sistema
#     resolve via sspi (mas R/httr não tem suporte built-in — pode precisar de
#     `cntlm` local como bridge).
#   - Proxy faz MITM e cert corporativo bloqueia: mude SSL_VERIFY pra FALSE.
#     Começa com TRUE; só desativa se der erro "SSL certificate problem".

# --- HTTP proxy (mandatório se quiser usar proxy) ---
PROXY_HOST <- ""          # ex.: "proxy.minhainstituicao.br"
PROXY_PORT <- ""          # ex.: "8080"

# --- HTTPS proxy (opcional: só preenche se for DIFERENTE do HTTP) ---
HTTPS_PROXY_HOST   <- ""  # vazio = usa o mesmo PROXY_HOST acima
HTTPS_PROXY_PORT   <- ""  # vazio = usa o mesmo PROXY_PORT acima
HTTPS_PROXY_SCHEME <- "http"  # quase sempre "http"; só "https" se canal até proxy for TLS

# --- Autenticação (opcional) ---
PROXY_USER <- ""          # vazio se não tiver auth básica
PROXY_PASS <- ""

# --- Verificação SSL (deixe TRUE; mude pra FALSE só se proxy fizer MITM) ---
SSL_VERIFY <- TRUE

# ---------------------------------------------------------------------------
# Não mexa daqui pra baixo.

.mk_proxy_url <- function(scheme, host, port, user, pass) {
  cred <- if (nzchar(user)) {
    sprintf("%s:%s@",
            utils::URLencode(user, reserved = TRUE),
            utils::URLencode(pass, reserved = TRUE))
  } else ""
  sprintf("%s://%s%s:%s", scheme, cred, host, port)
}

if (nzchar(PROXY_HOST) && nzchar(PROXY_PORT)) {
  http_url <- .mk_proxy_url("http", PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS)

  https_host <- if (nzchar(HTTPS_PROXY_HOST)) HTTPS_PROXY_HOST else PROXY_HOST
  https_port <- if (nzchar(HTTPS_PROXY_PORT)) HTTPS_PROXY_PORT else PROXY_PORT
  https_url  <- .mk_proxy_url(HTTPS_PROXY_SCHEME, https_host, https_port,
                              PROXY_USER, PROXY_PASS)

  Sys.setenv(http_proxy = http_url, https_proxy = https_url)
  if (requireNamespace("httr", quietly = TRUE)) {
    # httr::use_proxy aplica em todo request subsequente. Como nossos endpoints
    # são todos HTTPS (BCB/IBGE), apontamos pra config HTTPS.
    httr::set_config(httr::use_proxy(
      url      = sprintf("%s://%s", HTTPS_PROXY_SCHEME, https_host),
      port     = as.integer(https_port),
      username = if (nzchar(PROXY_USER)) PROXY_USER else NULL,
      password = if (nzchar(PROXY_PASS)) PROXY_PASS else NULL
    ), override = FALSE)
  }
  cat(sprintf("[PROXY] http  %s:%s\n", PROXY_HOST, PROXY_PORT))
  cat(sprintf("[PROXY] https %s://%s:%s%s\n",
              HTTPS_PROXY_SCHEME, https_host, https_port,
              if (nzchar(PROXY_USER)) sprintf(" (user=%s)", PROXY_USER) else ""))
}

if (!isTRUE(SSL_VERIFY) && requireNamespace("httr", quietly = TRUE)) {
  httr::set_config(httr::config(ssl_verifypeer = 0L, ssl_verifyhost = 0L),
                   override = FALSE)
  cat("[PROXY] SSL verify DESABILITADO (cert corporativo). Use só em rede confiável.\n")
}
