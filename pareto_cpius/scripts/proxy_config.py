# proxy_config.py — sourceado pelos scripts Python que fazem HTTP.
# Reusa o `proxy_config.R` que ja esta preenchido no corp — parseia as
# atribuicoes R (`PROXY_HOST <- "..."`, etc.) e traduz pra env vars Python.
# UX: fillado 1x no proxy_config.R e vale pros scripts R e Python igualmente.
#
# Ordem de fallback pra achar o R config:
#   1) $DIR/proxy_config.R (mesmo diretorio)
#   2) $ROOT/scripts/proxy_config.R (raiz do projeto atual)
#   3) ../pareto_ipca15/scripts/proxy_config.R (fonte canonica)
#   4) ../pareto_ipca/scripts/proxy_config.R
#
# Se nada existir, no-op. Se existir mas PROXY_HOST vazio, no-op.

import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_R_CFG_CANDIDATES = [
    _HERE / "proxy_config.R",
    _HERE.parent / "scripts" / "proxy_config.R",
    _HERE.parent.parent / "pareto_ipca15" / "scripts" / "proxy_config.R",
    _HERE.parent.parent / "pareto_ipca" / "scripts" / "proxy_config.R",
    _HERE.parent.parent / "pareto_cpius" / "scripts" / "proxy_config.R",
]


def _parse_r_config(path: Path) -> dict:
    """Extrai atribuicoes R `VAR <- "valor"`. Strip comentarios inline antes."""
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        # Strip inline comment (# ate fim da linha). R nao tem # dentro de
        # strings no template atual, entao naive split e' safe.
        no_comment = re.split(r'\s+#', line, maxsplit=1)[0]
        m = re.match(r'^\s*([A-Z_][A-Z0-9_]*)\s*<-\s*(.+?)\s*$', no_comment)
        if not m:
            continue
        name, raw = m.group(1), m.group(2).strip()
        if (raw.startswith('"') and raw.endswith('"')) or \
           (raw.startswith("'") and raw.endswith("'")):
            out[name] = raw[1:-1]
        elif raw in ("TRUE", "FALSE"):
            out[name] = (raw == "TRUE")
        else:
            out[name] = raw
    return out


_r_path = next((p for p in _R_CFG_CANDIDATES if p.exists()), None)
if _r_path is None:
    # Sem config disponivel — no-op.
    pass
else:
    _cfg = _parse_r_config(_r_path)
    PROXY_HOST = _cfg.get("PROXY_HOST", "")
    PROXY_PORT = _cfg.get("PROXY_PORT", "")
    HTTPS_PROXY_HOST   = _cfg.get("HTTPS_PROXY_HOST", "")
    HTTPS_PROXY_PORT   = _cfg.get("HTTPS_PROXY_PORT", "")
    HTTPS_PROXY_SCHEME = _cfg.get("HTTPS_PROXY_SCHEME", "http")
    PROXY_USER = _cfg.get("PROXY_USER", "")
    PROXY_PASS = _cfg.get("PROXY_PASS", "")
    SSL_VERIFY = _cfg.get("SSL_VERIFY", True)

    if PROXY_HOST and PROXY_PORT:
        from urllib.parse import quote as _urlquote

        def _mk(scheme, host, port, user, pw):
            cred = f"{_urlquote(user, safe='')}:{_urlquote(pw, safe='')}@" if user else ""
            return f"{scheme}://{cred}{host}:{port}"

        _http = _mk("http", PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS)
        _https_host = HTTPS_PROXY_HOST or PROXY_HOST
        _https_port = HTTPS_PROXY_PORT or PROXY_PORT
        _https = _mk(HTTPS_PROXY_SCHEME, _https_host, _https_port,
                     PROXY_USER, PROXY_PASS)
        # Uppercase + lowercase por compat (urllib/requests picam ambos).
        os.environ["HTTP_PROXY"]  = _http
        os.environ["HTTPS_PROXY"] = _https
        os.environ["http_proxy"]  = _http
        os.environ["https_proxy"] = _https
        print(f"[PROXY] usando config de {_r_path.name}")
        print(f"[PROXY] http  {PROXY_HOST}:{PROXY_PORT}")
        _cred_msg = f" (user={PROXY_USER})" if PROXY_USER else ""
        print(f"[PROXY] https {HTTPS_PROXY_SCHEME}://{_https_host}:{_https_port}{_cred_msg}")

    if SSL_VERIFY is False:
        os.environ["PYTHONHTTPSVERIFY"] = "0"
        try:
            import ssl as _ssl
            _ssl._create_default_https_context = _ssl._create_unverified_context
        except Exception:
            pass
        print("[PROXY] SSL verify DESABILITADO (cert corp). Use so em rede confiavel.")
