"""
Atualização pelo calendário — lê os releases do dia na tabela
OPT_Macro_Calendar (alimentada pelo calendário Bloomberg, a mesma que o site
do escritório usa) e descobre quais books (OPT_Macro_Reports) precisam ser
atualizados.

O elo entre os dois é o arquivo `calendar_books.csv`, ao lado do exe:

    pais;indicador;book
    United States;Change in Nonfarm Payrolls;US Payroll
    United States;Unemployment Rate;US Payroll
    United States;U. of Mich. Sentiment;University of Michigan Sentiment
    Czech Republic;Industrial Output YoY;-

- `pais` é o country_name do calendário; `*` vale para qualquer país.
- `indicador` é a coluna `indicator` da query do site
  (ISNULL(indicator, ISNULL(event_alias, event_name))).
- `book` é o nome exato do relatório no MacroScheduler. `-` (ou vazio)
  quer dizer "conheço este indicador, não tem book": ele some da lista de
  pendências.
- Maiúsculas/minúsculas e espaços nas pontas não importam.
- Linhas começando com `#` são comentários.

Abre no Excel ou no Bloco de Notas. A aba "Calendário" também grava aqui
(botão "Vincular a book").

Sem PyQt aqui: usado pela GUI e pelo modo headless (run_dev.py --calendar).
"""
from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

from local_pipelines import app_dir

MAPPING_FILE = "calendar_books.csv"
IGNORE = "-"
HEADER = ["pais", "indicador", "book"]

# Usado só se o calendar_books.csv não existir ao lado do exe: o app cria o
# arquivo com este conteúdo. Depois disso, vale o que estiver no arquivo.
DEFAULT_CSV = """\
# Mapeamento indicador do calendário Bloomberg -> book do MacroScheduler.
# pais = country_name do calendário (* = qualquer país)
# indicador = coluna indicator (nome do dado como aparece no calendário)
# book = nome exato do relatório; '-' = sem book (não atualiza e não aparece como pendente)
pais;indicador;book
United States;Change in Nonfarm Payrolls;US Payroll
United States;Change in Manuf. Payrolls;US Payroll
United States;Unemployment Rate;US Payroll
United States;U. of Mich. Sentiment;University of Michigan Sentiment
"""

# SQL do site do calendário, com as mesmas regras de filtro. A relevância é
# opcional (parâmetro only_relevant) para permitir ver tudo do dia.
CALENDAR_SQL = """
SELECT country_name,
       ISNULL(event_alias, event_name) AS event_name,
       [period], release_date, release_time, release_date_time,
       ISNULL(indicator, ISNULL(event_alias, event_name)) AS indicator,
       ISNULL(optimus_relevancy, relevancy) AS relevancy,
       ROUND(survey_median, 2) AS survey_median,
       ROUND(actual, 2) AS actual,
       ROUND(prior, 2) AS prior
FROM OPT_Macro_Calendar
WHERE release_end_date >= ?
  AND release_date <= ?
  {relevancy_filter}
  AND country_name NOT IN ('Hong Kong', 'Austria', 'Greece', 'Netherlands')
ORDER BY release_date_time, country_name, event_name
"""

RELEVANCY_FILTER = """AND (ISNULL(optimus_relevancy, relevancy) IS NULL
       OR ISNULL(optimus_relevancy, relevancy) IN ('Very High', 'High'))"""


def _norm(s) -> str:
    return " ".join(str(s or "").split()).casefold()


# ──────────────────────────────────────────────────────────────────────
# Mapeamento (calendar_books.csv)
# ──────────────────────────────────────────────────────────────────────

def mapping_path() -> str:
    return os.environ.get("MACRO_CALENDAR_BOOKS") or os.path.join(app_dir(), MAPPING_FILE)


@dataclass
class Mapping:
    # (pais normalizado, indicador normalizado) -> book ('' = ignorar)
    rules: dict[tuple[str, str], str] = field(default_factory=dict)
    path: str = ""
    warnings: list[str] = field(default_factory=list)

    def book_for(self, country: str, indicator: str) -> str | None:
        """Nome do book, '' se marcado como sem book, None se não mapeado."""
        key = (_norm(country), _norm(indicator))
        if key in self.rules:
            return self.rules[key]
        return self.rules.get(("*", key[1]))

    def books(self) -> set[str]:
        return {b for b in self.rules.values() if b}


def ensure_mapping_file() -> str:
    path = mapping_path()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(DEFAULT_CSV)
    return path


def _read_text(path: str) -> tuple[str, str]:
    """Lê o CSV como UTF-8; se o Excel salvou em ANSI (cp1252), lê assim."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read(), "utf-8"
    except UnicodeDecodeError:
        with open(path, encoding="cp1252") as fh:
            return fh.read(), "cp1252"


def load_mapping() -> Mapping:
    path = ensure_mapping_file()
    m = Mapping(path=path)
    text, _enc = _read_text(path)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    # aceita ';' (Excel em português) ou ',' (Excel em inglês)
    delim = ";" if lines and lines[0].count(";") >= lines[0].count(",") else ","
    for n, row in enumerate(csv.reader(lines, delimiter=delim), 1):
        if n == 1 and [_norm(c) for c in row[:3]] == HEADER:
            continue
        if len(row) < 2:
            m.warnings.append(f"linha ignorada (faltam colunas): {delim.join(row)}")
            continue
        country, indicator = row[0].strip(), row[1].strip()
        book = row[2].strip() if len(row) > 2 else ""
        if book == IGNORE:
            book = ""
        if not indicator:
            continue
        key = (_norm(country) or "*", _norm(indicator))
        if key in m.rules and m.rules[key] != book:
            m.warnings.append(
                f"'{country};{indicator}' aparece duas vezes; vale a última ({book or IGNORE})")
        m.rules[key] = book
    return m


def add_mapping_rows(rows: list[tuple[str, str, str]]) -> str:
    """Acrescenta (pais, indicador, book) ao fim do CSV. book '' vira '-'."""
    path = ensure_mapping_file()
    text, enc = _read_text(path)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    delim = ";" if not lines or lines[0].count(";") >= lines[0].count(",") else ","
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delim, lineterminator="\n")
    for country, indicator, book in rows:
        w.writerow([country, indicator, book or IGNORE])
    sep = "" if text.endswith("\n") or not text else "\n"
    with open(path, "a", encoding=enc, newline="") as fh:
        fh.write(sep + buf.getvalue())
    return path


# ──────────────────────────────────────────────────────────────────────
# Calendário
# ──────────────────────────────────────────────────────────────────────

def fetch_calendar(session, day: date | str, only_relevant: bool = True) -> pd.DataFrame:
    d = day if isinstance(day, str) else day.strftime("%Y-%m-%d")
    sql = CALENDAR_SQL.format(relevancy_filter=RELEVANCY_FILTER if only_relevant else "")
    df = pd.read_sql(sql, session.conn, params=[d, d])
    df["release_date_time"] = pd.to_datetime(df["release_date_time"], errors="coerce")
    return df


@dataclass
class BookPlan:
    book: str
    first_release: datetime | None                # 1º release do dia que alimenta o book
    indicators: list[str] = field(default_factory=list)
    released: bool = False                         # algum desses já tem 'actual'?


def annotate(df: pd.DataFrame, mapping: Mapping, known_books: set[str] | None = None) -> pd.DataFrame:
    """Acrescenta as colunas book e status:
        ok          -> tem book e ele existe no banco
        sem_book    -> marcado com '-' no CSV
        nao_mapeado -> indicador não está no CSV
        book_inexistente -> CSV aponta para um nome que não está em OPT_Macro_Reports
    """
    df = df.copy()
    books, status = [], []
    known = {_norm(b): b for b in (known_books or [])}
    for country, ind in zip(df["country_name"], df["indicator"]):
        b = mapping.book_for(country, ind)
        if b is None:
            books.append(""); status.append("nao_mapeado")
        elif b == "":
            books.append(""); status.append("sem_book")
        elif known_books is not None and _norm(b) not in known:
            books.append(b); status.append("book_inexistente")
        else:
            books.append(known.get(_norm(b), b)); status.append("ok")
    df["book"] = books
    df["status"] = status
    return df


def plan_books(annotated: pd.DataFrame) -> list[BookPlan]:
    plans: dict[str, BookPlan] = {}
    for _, r in annotated[annotated["status"] == "ok"].iterrows():
        p = plans.setdefault(r["book"], BookPlan(book=r["book"], first_release=None))
        ts = r["release_date_time"]
        ts = None if pd.isna(ts) else ts.to_pydatetime()
        if ts is not None and (p.first_release is None or ts < p.first_release):
            p.first_release = ts
        label = f"{r['indicator']}"
        if label not in p.indicators:
            p.indicators.append(label)
        if pd.notna(r.get("actual")):
            p.released = True
    return sorted(plans.values(), key=lambda p: (p.first_release or datetime.max, p.book))


_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec"]


def uk_labor_month_for(day: date | datetime) -> str:
    """Mês usado nas URLs do ONS (a01nov2026.xls): o mês da divulgação.
    Não depende do locale do Windows (strftime('%b') dependeria)."""
    return _MONTHS[day.month - 1]


def schedule_slots(plans: list[BookPlan], delay_minutes: int,
                   now: datetime | None = None) -> tuple[dict[datetime, list[str]], list[str]]:
    """Agrupa os books pelo horário de execução (1º release + atraso).
    Devolve ({horário: [books]}, [books cujo horário já passou])."""
    now = now or datetime.now()
    slots: dict[datetime, list[str]] = {}
    past: list[str] = []
    for p in plans:
        if p.first_release is None:
            past.append(p.book)
            continue
        when = (p.first_release + timedelta(minutes=delay_minutes)).replace(second=0, microsecond=0)
        if when < now.replace(second=0, microsecond=0):
            past.append(p.book)
        else:
            slots.setdefault(when, []).append(p.book)
    return dict(sorted(slots.items())), past
