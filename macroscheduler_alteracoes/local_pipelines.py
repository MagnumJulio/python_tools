"""
Rodagem local — executa os pipelines do repositório `python_tools`
(pareto_ipca, pareto_ipca15, pareto_cpius, pareto_pce) de dentro do
MacroScheduler, como alternativa ao Haver/Bloomberg: os scripts baixam
das fontes públicas (IBGE/SIDRA, BLS, BEA, Fed regionais) e gravam nas
mesmas tabelas OPT_Macro_Series_2 / OPT_Macro_Series_Data_2.

Cada pipeline vira uma lista ordenada de passos (comando + pasta), copiada
dos RUNBOOKs do python_tools. O runner roda cada passo como subprocesso,
transmite o stdout para o log da GUI e para no primeiro erro.

Sem PyQt aqui: este módulo é usado tanto pela GUI quanto pelo modo headless.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# ──────────────────────────────────────────────────────────────────────
# Configuração local (pasta do python_tools, executáveis, chaves de API)
# ──────────────────────────────────────────────────────────────────────

SETTINGS_FILE = "local_settings.json"

DEFAULT_SETTINGS = {
    "python_tools_dir": "",
    "python_exe": "",          # vazio = o mesmo Python que roda o MacroScheduler
    "rscript_cmd": "Rscript",  # pode ser caminho completo (ex.: C:\\Program Files\\R\\R-4.4\\bin\\Rscript.exe)
    "BLS_API_KEY": "",
    "BEA_API_KEY": "",
    # Aba Calendário (calendar_books.py)
    "calendar_auto": False,          # agendar sozinho todo dia
    "calendar_auto_time": "07:00",   # horário em que o app lê o calendário do dia
    "calendar_delay_min": 1,         # minutos depois do release para rodar o book
    "calendar_only_relevant": True,  # só High/Very High, como no site
}


def app_dir() -> str:
    """Pasta onde fica o exe (PyInstaller) ou o código-fonte."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def settings_path() -> str:
    return os.environ.get("MACRO_LOCAL_SETTINGS") or os.path.join(app_dir(), SETTINGS_FILE)


def load_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if k in DEFAULT_SETTINGS})
    except FileNotFoundError:
        pass
    except Exception as e:  # json inválido: não derruba a GUI
        print(f"[local_pipelines] aviso: {settings_path()} ilegível ({e}); usando padrões")
    return cfg


def save_settings(cfg: dict) -> None:
    data = {k: cfg.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}
    with open(settings_path(), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────
# Passos e pipelines
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Step:
    label: str
    argv: list[str]            # argv[0] ∈ {"python", "Rscript"} — resolvido pelo runner
    cwd: str                   # relativo à raiz do python_tools (ex.: "pareto_ipca")
    kind: str = "build"        # "build" (fetch/calc local), "load" (grava SQL), "fix" (pós-carga SQL)
    optional: bool = False     # falha não interrompe o pipeline (passos "fix" são sempre opcionais)
    group: str = ""            # passos do mesmo grupo são pulados quando um deles falha (ex.: build + load)

    def __post_init__(self):
        if self.kind == "fix" or self.group:
            self.optional = True


@dataclass
class PipelineOptions:
    scope: str = "dashboard"   # "dashboard" (subset dos runbooks) | "full"
    sa: bool = True            # IPCA/IPCA-15: também carrega idx SA (X-13)
    cpius_extras: bool = True  # CPI-U: alt measures + bottom-up + difusão + breadth
    cpius_oer: bool = False    # CPI-U: OER regional
    pce_fed: bool = False      # PCE: alt measures scraped (Cleveland/Dallas já publicaram)


# Subsets dos RUNBOOK_ATUALIZACAO_* (copiados literalmente)
IPCA_DASHBOARD_CATS = (
    "total,alim_e_bebidas,alim_domicilio,alim_fora,habitacao,energia_eletrica,"
    "artigos_residencia,vestuario,transportes,passagem_aerea,auto_novo,auto_usado,"
    "gasolina,saude,higiene_pessoal,despesas_pessoais,educacao,comunicacao,"
    "administrados,industriais,servicos"
)
CPIUS_DASHBOARD_CATS = (
    "all_items,core,airline_fares,core_ex_oer,core_services_ex_shelter,"
    "core_services_ex_volatiles,cpi_ex_oer,energy,food,lodging_away,medical_services,"
    "new_vehicles,oer,rent,shelter,super_super_core,supercore_powell_old,"
    "transportation_services,used_cars_trucks,car_truck_rental,core_goods,core_services"
)


def _only(scope: str, cats: str) -> list[str]:
    return [] if scope == "full" else ["--only", cats]


def _ipca_like(d: str, label: str, opt: PipelineOptions) -> list[Step]:
    """IPCA cheio e IPCA-15 têm o mesmo esqueleto (pareto_ipca / pareto_ipca15)."""
    only = _only(opt.scope, IPCA_DASHBOARD_CATS)
    steps = [
        Step(f"{label}: SIDRA últimos 24 meses", ["Rscript", "scripts/reconstruct_ipca.R", "--no-bcb"], d),
        Step(f"{label}: rebase do índice", ["Rscript", "scripts/build_pareto_indice.R"], d),
        Step(f"{label}: carga NSA (idx + Weight)", ["python", "script_itau/load_pareto_to_sql.py", *only], d, "load"),
    ]
    if opt.sa:
        steps += [
            Step(f"{label}: carga SA (X-13)", ["python", "script_itau/load_pareto_to_sql.py", *only, "--sa"], d, "load"),
            Step(f"{label}: fix servicos idx SA", ["python", "script_itau/_fix_servicos_idx_sa.py"], d, "fix"),
        ]
        if d == "pareto_ipca":
            steps.append(Step(f"{label}: fix alim_dom SA", ["python", "script_itau/_fix_alim_dom_sa.py"], d, "fix"))
        if opt.scope == "full":
            steps += [
                Step(f"{label}: SA DP + núcleo médio (R seasonal)", ["Rscript", "scripts/_sa_dp_nucleo_medio.R"], d, "build", optional=True),
                Step(f"{label}: fix DP médio SA", ["python", "script_itau/_fix_dp_medio_sa.py"], d, "fix", optional=True),
                Step(f"{label}: fix núcleo médio SA", ["python", "script_itau/_fix_nucleo_medio_sa.py"], d, "fix", optional=True),
            ]
    return steps


def _ipca(opt: PipelineOptions) -> list[Step]:
    return _ipca_like("pareto_ipca", "IPCA", opt)


def _ipca15(opt: PipelineOptions) -> list[Step]:
    return _ipca_like("pareto_ipca15", "IPCA-15", opt)


def _cpius(opt: PipelineOptions) -> list[Step]:
    d = "pareto_cpius"
    only = _only(opt.scope, CPIUS_DASHBOARD_CATS)
    steps = [
        Step("CPI-U: fetch BLS idx (Table 1)", ["Rscript", "scripts/fetch_bls_cpiu.R"], d),
        Step("CPI-U: fetch pesos (RI Table 6)", ["Rscript", "scripts/fetch_bls_pesos.R"], d),
        Step("CPI-U: agregações custom (Laspeyres)", ["Rscript", "scripts/build_custom_aggregations.R"], d),
        Step("CPI-U: carga idx NSA/SA + Weight", ["python", "script_itau/load_cpius_to_sql.py", *only], d, "load"),
    ]
    # Extras dependem de fontes externas (FRED, Atlanta/Cleveland Fed): cada
    # par build+load é um grupo opcional — se o build falha, a carga é pulada
    # e o pipeline segue (o build já preserva o CSV anterior; não recarregar
    # dado velho).
    if opt.cpius_extras:
        steps += [
            Step("CPI-U: build alt measures (Atlanta/Cleveland)", ["python", "scripts/build_alt_measures_cpi.py"], d, group="cpius_alt"),
            Step("CPI-U: carga alt measures", ["python", "script_itau/load_alt_measures_cpi_to_sql.py"], d, "load", group="cpius_alt"),
            Step("CPI-U: build bottom-up (Trimmed Sym 25%)", ["python", "scripts/build_alt_bottomup_cpi.py"], d, group="cpius_bottomup"),
            Step("CPI-U: carga bottom-up", ["python", "script_itau/load_alt_bottomup_cpi_to_sql.py"], d, "load", group="cpius_bottomup"),
            Step("CPI-U: build difusão", ["python", "scripts/build_diffusion_cpius.py"], d, group="cpius_diff"),
            Step("CPI-U: carga difusão", ["python", "script_itau/load_diffusion_to_sql.py"], d, "load", group="cpius_diff"),
            Step("CPI-U: build breadth", ["python", "scripts/build_breadth_cpi.py"], d, group="cpius_breadth"),
            Step("CPI-U: carga breadth", ["python", "script_itau/load_breadth_cpi_to_sql.py"], d, "load", group="cpius_breadth"),
        ]
    if opt.cpius_oer:
        steps += [
            Step("CPI-U: fetch OER regional", ["Rscript", "scripts/fetch_bls_oer_regional.R"], d, group="cpius_oer"),
            Step("CPI-U: carga OER regional", ["python", "script_itau/load_oer_regional_to_sql.py"], d, "load", group="cpius_oer"),
        ]
    return steps


def _pce(opt: PipelineOptions) -> list[Step]:
    d = "pareto_pce"
    full = ["--full"] if opt.scope == "full" else []
    steps = [
        Step("PCE: fetch BEA (U20404 + U20405)", ["python", "scripts/fetch_pce.py"], d),
        Step("PCE: build categorias", ["python", "scripts/build_pce_categorias.py"], d),
        Step("PCE: build difusão", ["python", "scripts/build_diffusion.py"], d),
        Step("PCE: build breadth", ["python", "scripts/build_breadth_pce.py"], d),
        Step("PCE: build distribuição de altas", ["python", "scripts/build_altas_distribution_pce.py"], d),
        Step("PCE: build alt measures proxy", ["python", "scripts/build_alt_measures_pce_proxy.py", "--skip-benchmark"], d),
        Step("PCE: carga categorias (66 séries)", ["python", "script_itau/load_pce_categorias_to_sql.py"], d, "load"),
        Step("PCE: carga difusão", ["python", "script_itau/load_pce_to_sql.py"], d, "load"),
        Step("PCE: carga breadth", ["python", "script_itau/load_breadth_pce_to_sql.py", *full], d, "load"),
        Step("PCE: carga distribuição de altas", ["python", "script_itau/load_altas_distribution_pce_to_sql.py", *full], d, "load"),
        Step("PCE: carga alt measures proxy", ["python", "script_itau/load_alt_measures_pce_proxy_to_sql.py"], d, "load"),
    ]
    if opt.pce_fed:
        steps += [
            Step("PCE: build alt measures scraped (Cleveland + Dallas)", ["python", "scripts/build_alt_measures_pce.py"], d, group="pce_fed"),
            Step("PCE: carga alt measures scraped", ["python", "script_itau/load_alt_measures_pce_to_sql.py"], d, "load", group="pce_fed"),
        ]
    return steps


@dataclass(frozen=True)
class Pipeline:
    key: str
    name: str
    folder: str
    release_hint: str
    build: Callable[[PipelineOptions], list[Step]]


PIPELINES: dict[str, Pipeline] = {
    "ipca":   Pipeline("ipca",   "IPCA (IBGE)",     "pareto_ipca",   "dia 8-10 do mês seguinte, ~09:00", _ipca),
    "ipca15": Pipeline("ipca15", "IPCA-15 (IBGE)",  "pareto_ipca15", "~dia 24 do próprio mês, ~09:00",   _ipca15),
    "cpius":  Pipeline("cpius",  "CPI-U (BLS)",     "pareto_cpius",  "dia 10-15 do mês seguinte, ~09:30", _cpius),
    "pce":    Pipeline("pce",    "PCE (BEA)",       "pareto_pce",    "último dia útil do mês, ~09:30",    _pce),
}

# Nome que aparece na lista de agendamento, ao lado dos relatórios Haver/BBG
PIPELINE_PREFIX = "⚙ Pipeline local: "


def pipeline_display_name(key: str) -> str:
    return PIPELINE_PREFIX + PIPELINES[key].name


def pipeline_key_from_display(name: str) -> str | None:
    if not name.startswith(PIPELINE_PREFIX):
        return None
    wanted = name[len(PIPELINE_PREFIX):]
    for k, p in PIPELINES.items():
        if p.name == wanted:
            return k
    return None


# ──────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────

@dataclass
class LocalRunConfig:
    pipelines: list[str] = field(default_factory=list)   # chaves de PIPELINES
    options: PipelineOptions = field(default_factory=PipelineOptions)
    dry_run: bool = False      # loaders com --dry-run; passos "fix" são pulados
    settings: dict = field(default_factory=load_settings)
    stop_on_error: bool = True


def plan_steps(cfg: LocalRunConfig) -> list[Step]:
    steps: list[Step] = []
    for key in cfg.pipelines:
        for st in PIPELINES[key].build(cfg.options):
            if st.kind == "load":
                argv = list(st.argv) + ["--no-confirm"] + (["--dry-run"] if cfg.dry_run else [])
                st = Step(st.label, argv, st.cwd, st.kind, st.optional, st.group)
            elif st.kind == "fix" and cfg.dry_run:
                continue
            steps.append(st)
    return steps


def preflight(cfg: LocalRunConfig) -> list[str]:
    """Problemas que impedem a rodada (lista vazia = ok)."""
    errs: list[str] = []
    root = cfg.settings.get("python_tools_dir") or ""
    if not root or not os.path.isdir(root):
        errs.append(f"Pasta do python_tools não encontrada: '{root or '(vazio)'}'")
        return errs
    for key in cfg.pipelines:
        p = PIPELINES[key]
        if not os.path.isdir(os.path.join(root, p.folder)):
            errs.append(f"{p.name}: subpasta '{p.folder}' não existe em {root}")
    steps = plan_steps(cfg)
    if any(st.argv[0] == "Rscript" for st in steps):
        rcmd = _rscript_cmd(cfg.settings)
        if not rcmd or not (shutil.which(rcmd[0]) or os.path.isfile(rcmd[0])):
            errs.append(f"Rscript não encontrado ('{cfg.settings.get('rscript_cmd')}'). Instale o R ou aponte o caminho completo do Rscript.exe nas configurações.")
    if any(st.argv[0] == "python" for st in steps):
        pycmd = _python_cmd(cfg.settings)
        if not pycmd:
            errs.append("Nenhum Python encontrado (campo 'Python' vazio, nada no PATH). Informe o caminho do "
                        "python.exe do ambiente que tem opt_utils (ex.: C:\\Users\\...\\python.exe).")
        elif not (shutil.which(pycmd[0]) or os.path.isfile(pycmd[0])):
            errs.append(f"Python não encontrado: '{pycmd[0]}' (campo 'Python' = '{cfg.settings.get('python_exe')}')")
    return errs


def split_cmd(text: str) -> list[str]:
    """Quebra um comando configurado pelo usuário em argv.

    No Windows NÃO usa o modo POSIX do shlex: ele engole as barras
    invertidas (C:\\Python\\python.exe viraria C:Pythonpython.exe).
    Aceita caminho sem aspas, com aspas, ou com argumentos extras.
    """
    text = (text or "").strip()
    if not text:
        return []
    if os.path.isfile(text):              # caminho completo, com ou sem espaços
        return [text]
    parts = shlex.split(text, posix=(os.name != "nt"))
    return [p.strip('"') for p in parts]


def _python_cmd(settings: dict) -> list[str]:
    """Python que roda os scripts do python_tools.

    Ordem: campo 'Python' da configuração → variável MACRO_PYTHON → o próprio
    interpretador (quando o app roda do fonte) → 'python' no PATH → launcher
    'py -3' (Windows). Dentro do exe (PyInstaller) o interpretador embutido não
    serve, por isso os fallbacks.
    """
    exe = settings.get("python_exe") or os.environ.get("MACRO_PYTHON") or ""
    if exe:
        return split_cmd(exe)
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    found = shutil.which("python") or shutil.which("python3")
    if found:
        return [found]
    py = shutil.which("py")
    if py:
        return [py, "-3"]
    return []


def _rscript_cmd(settings: dict) -> list[str]:
    cmd = split_cmd(settings.get("rscript_cmd") or "Rscript")
    if cmd and not (shutil.which(cmd[0]) or os.path.isfile(cmd[0])) and os.name == "nt":
        # Rscript fora do PATH: procura a instalação padrão do R no Windows
        import glob
        for base in (r"C:\Program Files\R", r"C:\Program Files (x86)\R",
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "R")):
            hits = sorted(glob.glob(os.path.join(base, "R-*", "bin", "Rscript.exe")), reverse=True)
            if hits:
                return [hits[0]] + cmd[1:]
    return cmd


def check_environment(settings: dict, pipelines: Optional[list[str]] = None) -> list[tuple[bool, str]]:
    """Checagens que um usuário não-programador consegue ler: cada item é
    (ok, mensagem). Roda os executáveis de verdade (python -c / Rscript --version)."""
    out: list[tuple[bool, str]] = []
    root = settings.get("python_tools_dir") or ""
    if root and os.path.isdir(root):
        missing = [p.folder for p in PIPELINES.values() if not os.path.isdir(os.path.join(root, p.folder))]
        if missing:
            out.append((False, f"Pasta dos pipelines: {root} — faltam subpastas: {', '.join(missing)}"))
        else:
            out.append((True, f"Pasta dos pipelines: {root}"))
    else:
        out.append((False, f"Pasta dos pipelines não encontrada: '{root or '(vazio)'}'. Informe a pasta que contém pareto_ipca, pareto_cpius, etc."))

    env = _build_env(settings)
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}

    pycmd = _python_cmd(settings)
    if not pycmd:
        out.append((False, "Python: nenhum encontrado. Preencha o campo 'Python' com o caminho do python.exe "
                           "do ambiente que tem opt_utils (ex.: o que roda os load_*_to_sql.py hoje)."))
    else:
        probe = ("import sys, importlib.util; mods = ['pandas', 'requests', 'opt_utils.database']; "
                 "missing = [m for m in mods if importlib.util.find_spec(m.split('.')[0]) is None]; "
                 "print(sys.executable); print(','.join(missing))")
        try:
            r = subprocess.run(pycmd + ["-c", probe], capture_output=True, text=True, timeout=60, env=env, **kw)
            lines = (r.stdout or "").strip().splitlines()
            if r.returncode != 0 or not lines:
                out.append((False, f"Python: '{' '.join(pycmd)}' não respondeu ({(r.stderr or '').strip()[:200]})"))
            else:
                exe_real = lines[0]
                missing = [m for m in (lines[1] if len(lines) > 1 else "").split(",") if m]
                if missing:
                    out.append((False, f"Python: {exe_real} — faltam pacotes: {', '.join(missing)}. "
                                       "Use o Python do ambiente corporativo (o que tem opt_utils)."))
                else:
                    out.append((True, f"Python: {exe_real} (pandas, requests e opt_utils ok)"))
        except FileNotFoundError:
            out.append((False, f"Python: executável não encontrado: '{pycmd[0]}'"))
        except subprocess.TimeoutExpired:
            out.append((False, f"Python: '{pycmd[0]}' demorou mais de 60s para responder"))

    keys = pipelines if pipelines is not None else list(PIPELINES)
    needs_r = any(st.argv[0] == "Rscript" for k in keys for st in PIPELINES[k].build(PipelineOptions()))
    if needs_r:
        rcmd = _rscript_cmd(settings)
        try:
            r = subprocess.run(rcmd + ["--version"], capture_output=True, text=True, timeout=60, env=env, **kw)
            ver = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
            if r.returncode == 0:
                out.append((True, f"Rscript: {rcmd[0]} ({ver[0] if ver else 'ok'})"))
            else:
                out.append((False, f"Rscript: '{rcmd[0]}' falhou ao rodar --version"))
        except FileNotFoundError:
            out.append((False, f"Rscript não encontrado ('{settings.get('rscript_cmd') or 'Rscript'}'). "
                               "Instale o R ou informe o caminho completo do Rscript.exe."))
        except subprocess.TimeoutExpired:
            out.append((False, "Rscript demorou mais de 60s para responder"))

    for key, who in (("BLS_API_KEY", "CPI-U"), ("BEA_API_KEY", "PCE")):
        if settings.get(key) or os.environ.get(key):
            out.append((True, f"{key}: definida ({who})"))
        else:
            out.append((False, f"{key}: vazia — o pipeline {who} vai falhar ou cair em rate limit"))
    return out


def _build_env(settings: dict) -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONUNBUFFERED"] = "1"
    for k in ("BLS_API_KEY", "BEA_API_KEY"):
        if settings.get(k):
            env[k] = settings[k]
    # Dev (run_dev.py): loaders do python_tools enxergam o mock de opt_utils
    # (SQLite) e o x13as falso via PYTHONPATH, e gravam no mesmo dev.sqlite.
    mocks = env.get("MACRO_DEV_MOCKS")
    if mocks:
        env["PYTHONPATH"] = mocks + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else mocks
    # Proxy corporativo: reaproveita o do uk_labor se o ambiente não tiver
    try:
        import uk_labor
        prox = getattr(uk_labor, "_proxies", None) or {}
        if prox.get("http") and not env.get("HTTP_PROXY"):
            env["HTTP_PROXY"] = env["http_proxy"] = prox["http"]
        if prox.get("https") and not env.get("HTTPS_PROXY"):
            env["HTTPS_PROXY"] = env["https_proxy"] = prox["https"]
    except Exception:
        pass
    return env


class LocalPipelineRunner:
    def __init__(self, config: LocalRunConfig):
        self.config = config
        self._cancel = threading.Event()
        self._proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self._cancel.set()
        p = self._proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self, on_log: Callable[[str], None], on_progress: Callable[[int, int], None],
            on_finished: Callable[[bool, str], None]) -> None:
        cfg = self.config
        log = on_log
        try:
            errs = preflight(cfg)
            if errs:
                for e in errs:
                    log(f"✗ {e}")
                on_finished(False, "Pré-verificação falhou")
                return

            steps = plan_steps(cfg)
            if not steps:
                on_finished(False, "Nenhum passo a executar")
                return

            root = cfg.settings["python_tools_dir"]
            env = _build_env(cfg.settings)
            pycmd = _python_cmd(cfg.settings)
            rcmd = _rscript_cmd(cfg.settings)

            names = ", ".join(PIPELINES[k].name for k in cfg.pipelines)
            log("=" * 60)
            log(f"Rodagem local: {names}")
            log(f"  python_tools: {root}")
            log(f"  python: {' '.join(pycmd)}   |   Rscript: {' '.join(rcmd)}")
            log(f"  escopo: {cfg.options.scope}" + ("   [DRY-RUN: loaders só listam]" if cfg.dry_run else ""))
            log(f"  {len(steps)} passos")
            if env.get("MACRO_DEV_MOCKS"):
                log(f"  [dev] loaders usam o SQLite mock: {env.get('MACRO_DEV_DB', '(padrão dev_mocks/dev.sqlite)')}")
            log("=" * 60)

            ok_count = 0
            failed: list[str] = []
            skipped: list[str] = []
            failed_groups: set[str] = set()
            t0 = time.time()
            on_progress(0, len(steps))
            for i, st in enumerate(steps, 1):
                if self._cancel.is_set():
                    log("\n■ Cancelado pelo usuário.")
                    on_finished(False, f"Cancelado após {ok_count}/{len(steps)} passos")
                    return
                if st.group and st.group in failed_groups:
                    log(f"\n[{i}/{len(steps)}] ↷ {st.label} — pulado (passo anterior do grupo falhou)")
                    skipped.append(st.label)
                    on_progress(i, len(steps))
                    continue
                argv = (pycmd if st.argv[0] == "python" else rcmd) + st.argv[1:]
                cwd = os.path.join(root, st.cwd)
                log(f"\n[{i}/{len(steps)}] ▶ {st.label}")
                log(f"    $ {' '.join(shlex.quote(a) for a in st.argv)}   (em {st.cwd})")
                ts = time.time()
                rc = self._run_step(argv, cwd, env, log)
                dt = time.time() - ts
                if rc == 0:
                    ok_count += 1
                    log(f"    ✓ ok ({dt:.0f}s)")
                else:
                    tag = "aviso" if st.optional else "ERRO"
                    log(f"    ✗ {tag}: código de saída {rc} ({dt:.0f}s)")
                    failed.append(st.label)
                    if st.group:
                        failed_groups.add(st.group)
                    if not st.optional and cfg.stop_on_error and not self._cancel.is_set():
                        on_progress(i, len(steps))
                        on_finished(False, f"Falhou em '{st.label}' (passo {i}/{len(steps)})")
                        return
                on_progress(i, len(steps))

            total = time.time() - t0
            log("\n" + "=" * 60)
            if failed:
                log(f"⚠ CONCLUÍDO COM AVISOS — {ok_count}/{len(steps)} passos ok; falhas opcionais: {', '.join(failed)}")
                if skipped:
                    log(f"  pulados por dependência: {', '.join(skipped)}")
            else:
                log(f"✓ CONCLUÍDO — {ok_count}/{len(steps)} passos em {total/60:.1f} min")
            log("=" * 60)
            on_finished(True, f"{ok_count}/{len(steps)} passos ok")
        except Exception as e:
            log(f"\n✗ Erro inesperado: {e}")
            on_finished(False, str(e))

    def _run_step(self, argv: list[str], cwd: str, env: dict, log) -> int:
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: sem console piscando no exe
        try:
            self._proc = subprocess.Popen(
                argv, cwd=cwd, env=env,
                stdin=subprocess.DEVNULL,          # input() de loader sem --no-confirm falha em vez de travar
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, **kw,
            )
        except (FileNotFoundError, OSError) as e:
            log(f"    ✗ executável não encontrado: '{argv[0]}' ({e})")
            log("      → confira os campos 'Python' / 'Rscript' na Configuração da aba (caminho completo do .exe)")
            return 127
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            log("    " + line.rstrip("\n"))
        rc = self._proc.wait()
        if self._cancel.is_set() and rc != 0:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        return rc
