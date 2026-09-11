# proxy_config.py — sourceado pelos scripts Python que fazem HTTP.
# Analogo do proxy_config.R (mesmo padrao dos pipelines R).
#
# Edite os campos abaixo na maquina institucional. Sem este arquivo (ou com
# PROXY_HOST = "" abaixo), os scripts rodam SEM proxy — util em casa.
#
# ATENCAO: nao commitar credenciais reais. Este arquivo eh template — mantenha
# os defaults vazios no git. Preencher SO na copia local da maquina corp.
#
# Caso comum (mesmo proxy pra HTTP e HTTPS, sem auth):
#   preenche PROXY_HOST + PROXY_PORT e pronto.
#
# Casos especiais:
#   - Hosts/portas DIFERENTES pra HTTP e HTTPS: preencha HTTPS_PROXY_HOST/PORT.
#     Senao deixa vazio que herda de PROXY_HOST/PORT.
#   - Canal ate o proxy e TLS (raro): mude HTTPS_PROXY_SCHEME pra "https".
#   - Auth basica (user/senha no proxy): preenche PROXY_USER/PASS.
#   - Auth NTLM/Kerberos integrada ao Windows: deixa USER/PASS vazios; sistema
#     resolve via sspi (mas Python nao tem suporte built-in — pode precisar de
#     `cntlm` local como bridge).
#   - Proxy faz MITM e cert corporativo bloqueia: mude SSL_VERIFY pra False.
#     Comeca com True; so desativa se der erro "SSL certificate problem".

# --- HTTP proxy (mandatorio se quiser usar proxy) ---
PROXY_HOST = ""            # ex.: "proxy.minhainstituicao.br"
PROXY_PORT = ""            # ex.: "8080"

# --- HTTPS proxy (opcional: so preenche se for DIFERENTE do HTTP) ---
HTTPS_PROXY_HOST   = ""    # vazio = usa o mesmo PROXY_HOST acima
HTTPS_PROXY_PORT   = ""    # vazio = usa o mesmo PROXY_PORT acima
HTTPS_PROXY_SCHEME = "http"  # quase sempre "http"; so "https" se canal ate proxy for TLS

# --- Autenticacao (opcional) ---
PROXY_USER = ""            # vazio se nao tiver auth basica
PROXY_PASS = ""

# --- Verificacao SSL (deixe True; mude pra False so se proxy fizer MITM) ---
SSL_VERIFY = True

# ---------------------------------------------------------------------------
# Nao mexer daqui pra baixo.
#
# Como o exec() do carregador passa {"os": os} como globals, `os` esta
# disponivel aqui. Setamos env vars maiusculas (HTTPS_PROXY / HTTP_PROXY) —
# urllib/requests respeitam por default.

from urllib.parse import quote as _urlquote  # noqa: E402


def _mk_proxy_url(scheme, host, port, user, pw):
    cred = ""
    if user:
        cred = f"{_urlquote(user, safe='')}:{_urlquote(pw, safe='')}@"
    return f"{scheme}://{cred}{host}:{port}"


if PROXY_HOST and PROXY_PORT:
    _http = _mk_proxy_url("http", PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS)
    _https_host = HTTPS_PROXY_HOST or PROXY_HOST
    _https_port = HTTPS_PROXY_PORT or PROXY_PORT
    _https = _mk_proxy_url(HTTPS_PROXY_SCHEME, _https_host, _https_port,
                            PROXY_USER, PROXY_PASS)
    # Uppercase eh o que urllib/requests picam por default; lowercase por
    # compat com codigo que usa http_proxy/https_proxy (WSL/curl).
    os.environ["HTTP_PROXY"]  = _http
    os.environ["HTTPS_PROXY"] = _https
    os.environ["http_proxy"]  = _http
    os.environ["https_proxy"] = _https
    print(f"[PROXY] http  {PROXY_HOST}:{PROXY_PORT}")
    _cred_msg = f" (user={PROXY_USER})" if PROXY_USER else ""
    print(f"[PROXY] https {HTTPS_PROXY_SCHEME}://{_https_host}:{_https_port}{_cred_msg}")

if not SSL_VERIFY:
    # Best-effort: seta PYTHONHTTPSVERIFY e desabilita warnings do urllib3.
    # Codigo cliente que usar requests precisa passar verify=False; urllib
    # respeitas PYTHONHTTPSVERIFY=0 na maioria dos casos.
    os.environ["PYTHONHTTPSVERIFY"] = "0"
    try:
        import ssl as _ssl
        _ssl._create_default_https_context = _ssl._create_unverified_context
    except Exception:
        pass
    print("[PROXY] SSL verify DESABILITADO (cert corporativo). Use so em rede confiavel.")
