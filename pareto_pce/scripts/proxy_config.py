# proxy_config.py — sourceado pelos scripts Python que fazem HTTP.
# Analogo do proxy_config.R dos pipelines R. Ver
# pareto_cpius/scripts/proxy_config.py pra template completo.
#
# ATENCAO: nao commitar credenciais reais. Este arquivo eh template — mantenha
# os defaults vazios no git. Preencher SO na copia local da maquina corp.

# --- HTTP proxy (mandatorio se quiser usar proxy) ---
PROXY_HOST = ""            # ex.: "proxy.minhainstituicao.br"
PROXY_PORT = ""            # ex.: "8080"

# --- HTTPS proxy (opcional: so preenche se for DIFERENTE do HTTP) ---
HTTPS_PROXY_HOST   = ""
HTTPS_PROXY_PORT   = ""
HTTPS_PROXY_SCHEME = "http"

# --- Autenticacao (opcional) ---
PROXY_USER = ""
PROXY_PASS = ""

# --- Verificacao SSL (deixe True; mude pra False so se proxy fizer MITM) ---
SSL_VERIFY = True

# ---------------------------------------------------------------------------
# Nao mexer daqui pra baixo.

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
    os.environ["HTTP_PROXY"]  = _http
    os.environ["HTTPS_PROXY"] = _https
    os.environ["http_proxy"]  = _http
    os.environ["https_proxy"] = _https
    print(f"[PROXY] http  {PROXY_HOST}:{PROXY_PORT}")
    _cred_msg = f" (user={PROXY_USER})" if PROXY_USER else ""
    print(f"[PROXY] https {HTTPS_PROXY_SCHEME}://{_https_host}:{_https_port}{_cred_msg}")

if not SSL_VERIFY:
    os.environ["PYTHONHTTPSVERIFY"] = "0"
    try:
        import ssl as _ssl
        _ssl._create_default_https_context = _ssl._create_unverified_context
    except Exception:
        pass
    print("[PROXY] SSL verify DESABILITADO (cert corporativo). Use so em rede confiavel.")
