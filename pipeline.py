"""
opentool-watch: periodic discovery of papers on a topic from OpenAlex, with a pre-screen
for released code or weights. The topic is defined entirely in the config file.

Stages
  1. discover   query OpenAlex for each configured search (cursor pagination)
  2. dedup      store every paper once in a SQLite file, keyed on the OpenAlex ID
  3. screen     look for code/weights links in the abstract, then in OpenAlex's full text
  4. export     write a review queue (CSV), a PaperSnitch input list and dashboard.html

Run:  python pipeline.py --config config.yaml --data ./data
Env:  OPENALEX_MAILTO  your e-mail (OpenAlex asks scripts to identify themselves)
      OPENALEX_API_KEY required since Feb 2026 (free: https://openalex.org/settings/api)
"""

import argparse
import csv
import datetime as dt
import difflib
import io
import logging
import os
import re
import sqlite3
import time
import unicodedata

import requests
import yaml
from pypdf import PdfReader

import dashboard

API = "https://api.openalex.org/works"
FIELDS = ",".join([
    "id", "doi", "title", "publication_date", "type", "cited_by_count",
    "primary_location", "best_oa_location", "abstract_inverted_index", "authorships",
])
log = logging.getLogger("opentool-watch")


# ---------------------------------------------------------------- HTTP helpers

def get_with_retry(session, url, params=None, stream=False, tries=5):
    """GET with exponential backoff on rate limits (429) and server errors (5xx)."""
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=60, stream=stream)
        except requests.RequestException as e:
            log.warning("request error %s (attempt %d)", e, attempt + 1)
        else:
            if r.status_code == 200:
                return r
            if r.status_code in (401, 403) and url == API:
                log.error("OpenAlex refused the request (HTTP %s): set OPENALEX_API_KEY "
                          "(free key at https://openalex.org/settings/api)", r.status_code)
                return None
            if r.status_code not in (429, 500, 502, 503, 504):
                log.warning("HTTP %s for %s", r.status_code, url)
                return None
            log.warning("HTTP %s, retrying", r.status_code)
        time.sleep(2 ** attempt)
    return None


# ---------------------------------------------------------------- 1. discover

def openalex_get(session, params):
    """One /works request with the polite-pool e-mail and the API key added. Returns JSON."""
    params = dict(params)
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    r = get_with_retry(session, API, params=params)
    if r is None:
        raise RuntimeError(f"OpenAlex request failed: {params.get('filter', '')}")
    return r.json()


SEARCH_IN = ("title_and_abstract", "all_text")


def query_args(query, search_in):
    """Turn a configured query into (search parameter, filter) for OpenAlex.

    OpenAlex's `search` parameter matches title, abstract *and* full text, so any paper that
    mentions the terms anywhere (e.g. in its references) qualifies. The
    `title_and_abstract.search` filter takes the same Boolean syntax but only looks at the
    title and abstract: far fewer off-topic papers, at some cost in recall.
    """
    q = " ".join(query.split())
    if search_in == "all_text":
        return q, None
    if search_in == "title_and_abstract":
        if "," in q:  # a comma would end the filter and start a new one
            raise ValueError(f"remove the comma from query {q!r}: commas are not allowed "
                             "when search_in is title_and_abstract")
        return None, f"title_and_abstract.search:{q}"
    raise ValueError(f"search_in must be one of {', '.join(SEARCH_IN)}, not {search_in!r}")


def join_filters(*filters):
    return ",".join(f for f in filters if f) or None


def fetch_page(session, query, from_date, types, cursor, extra_filter=None, select=FIELDS):
    """One OpenAlex page. Returns (results, next_cursor)."""
    filters = f"from_publication_date:{from_date},type:{'|'.join(types)}"
    if extra_filter:
        filters += "," + extra_filter
    params = {"filter": filters, "per-page": 200, "cursor": cursor, "select": select}
    if query:  # None when the query is a title_and_abstract.search filter instead
        params["search"] = query
    data = openalex_get(session, params)
    return data.get("results", []), data.get("meta", {}).get("next_cursor")


def discover(session, query, from_date, types, extra_filter=None, select=FIELDS):
    """Follow the cursor until OpenAlex returns no next page."""
    cursor = "*"
    while cursor:
        results, cursor = fetch_page(session, query, from_date, types, cursor,
                                     extra_filter, select)
        yield from results
        time.sleep(0.2)  # be polite


def abstract_text(inverted_index):
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the plain text."""
    if not inverted_index:
        return ""
    positions = [(p, w) for w, ps in inverted_index.items() for p in ps]
    return " ".join(w for _, w in sorted(positions))


# ---------------------------------------------------------------- 2. dedup

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY, doi TEXT, title TEXT, publication_date TEXT, type TEXT,
    venue TEXT, landing_url TEXT, oa_pdf_url TEXT, cited_by INTEGER,
    queries TEXT, first_seen TEXT,
    code_urls TEXT, code_source TEXT, screened INTEGER DEFAULT 0, screened_on TEXT
);
CREATE TABLE IF NOT EXISTS runs (run_date TEXT PRIMARY KEY, new_papers INTEGER);
"""

# Columns added after the first release. Never drop or rename: existing databases are
# upgraded in place by open_db, and old rows simply start with the default.
ADDED_COLUMNS = {
    "first_author": "TEXT",            # full name, lower case, accents/punctuation removed
    "duplicate_of": "TEXT",            # OpenAlex ID of a likely preprint/published twin
    "duplicate_score": "REAL",         # title similarity, 0-1
    "dup_checked": "INTEGER DEFAULT 0",
}


def open_db(path):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    have = {row[1] for row in db.execute("PRAGMA table_info(papers)")}
    for name, decl in ADDED_COLUMNS.items():
        if name not in have:
            db.execute(f"ALTER TABLE papers ADD COLUMN {name} {decl}")
    db.commit()
    return db


def first_author(work):
    """First author's name, normalised for comparison ('J. Müller' -> 'j muller')."""
    for a in work.get("authorships") or []:
        if a.get("author_position") == "first":
            name = (a.get("author") or {}).get("display_name") or ""
            ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
            return " ".join(re.sub(r"[^a-z]+", " ", ascii_name.lower()).split()) or None
    return None


def same_author(a, b):
    """Names share a word of 2+ letters: 'rossi m' ~ 'mario rossi'. Word order varies."""
    if not a or not b:
        return False
    return bool({w for w in a.split() if len(w) > 1} & {w for w in b.split() if len(w) > 1})


def last_run_date(db):
    row = db.execute("SELECT MAX(run_date) FROM runs").fetchone()
    return row[0]


def upsert(db, work, query_name, today):
    """Insert a new paper, or record that another query also found it. Returns True if new."""
    row = db.execute("SELECT queries, first_author FROM papers WHERE id = ?",
                     (work["id"],)).fetchone()
    if row:
        names = set(row[0].split(","))
        if query_name not in names:
            names.add(query_name)
            db.execute("UPDATE papers SET queries = ? WHERE id = ?",
                       (",".join(sorted(names)), work["id"]))
        if row[1] is None:  # stored before first_author existed; fill it in now
            db.execute("UPDATE papers SET first_author = ? WHERE id = ?",
                       (first_author(work), work["id"]))
        return False
    primary = work.get("primary_location") or {}
    best_oa = work.get("best_oa_location") or {}
    db.execute(
        "INSERT INTO papers (id, doi, title, publication_date, type, venue, landing_url,"
        " oa_pdf_url, cited_by, queries, first_seen, first_author)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            work["id"], work.get("doi"), work.get("title"), work.get("publication_date"),
            work.get("type"), ((primary.get("source") or {}).get("display_name")),
            primary.get("landing_page_url"), best_oa.get("pdf_url"),
            work.get("cited_by_count"), query_name, today, first_author(work),
        ),
    )
    return True


def norm_title(title):
    """Lower case, no markup or punctuation, single spaces: for similarity only."""
    t = re.sub(r"<[^>]+>", " ", title or "")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def flag_duplicates(db, strong, weak):
    """Link each unchecked paper to its most similar preprint/non-preprint counterpart.

    OpenAlex often keeps a preprint and its published version as separate works, and the
    title may change on publication. A pair is flagged when title similarity >= strong, or
    >= weak with the same first author. Papers are never merged: the reviewer decides.
    """
    rows = db.execute("SELECT id, type, title, first_author, dup_checked FROM papers").fetchall()
    sides = {"pre": [], "pub": []}
    for pid, ptype, title, author, _ in rows:
        sides["pre" if ptype == "preprint" else "pub"].append((pid, norm_title(title), author))
    # Comparing every pair is too slow on a first harvest, so only compare titles that share
    # at least two uncommon words (words in under 5% of that side's titles, e.g. a model name).
    index = {}
    for side, papers in sides.items():
        words = {}
        for k, (_, t, _) in enumerate(papers):
            for wd in set(t.split()):
                words.setdefault(wd, []).append(k)
        cap = max(5, len(papers) // 20)
        index[side] = {wd: ks for wd, ks in words.items() if len(ks) <= cap}
    flagged = 0
    for pid, ptype, title, author, checked in rows:
        if checked:
            continue
        mine = norm_title(title)
        side = "pub" if ptype == "preprint" else "pre"
        others, words = sides[side], index[side]
        shared = {}
        for wd in set(mine.split()):
            for k in words.get(wd, ()):
                shared[k] = shared.get(k, 0) + 1
        best, best_score = None, 0.0
        sm = difflib.SequenceMatcher(None, "", mine)  # seq2 is the cached side
        for k, n_shared in shared.items():
            oid, otitle, oauthor = others[k]
            if n_shared < 2:
                continue
            sm.set_seq1(otitle)
            score = sm.ratio()
            if (score >= strong or (same_author(author, oauthor) and score >= weak)) \
                    and score > best_score:
                best, best_score = oid, score
        db.execute("UPDATE papers SET duplicate_of = ?, duplicate_score = ?, dup_checked = 1"
                   " WHERE id = ?", (best, round(best_score, 2) if best else None, pid))
        flagged += best is not None
    db.commit()
    return flagged


# ---------------------------------------------------------------- 3. screen

def code_regex(hosts):
    host = "|".join(re.escape(h) for h in hosts)
    return re.compile(rf"https?://(?:www\.)?(?:{host})/[^\s\)\]\}}>,;\"']+", re.I)


def find_code_urls(text, rx):
    urls = {u.rstrip(".") for u in rx.findall(text or "")}
    return sorted(urls)


def fulltext_hits(session, queries, terms, from_date, types):
    # queries: (search, filter) pairs from query_args
    """IDs of works whose full text mentions one of the terms (e.g. 'github').

    OpenAlex searches its own full-text index, so no PDF is downloaded, but it only says
    *that* a term appears, not the URL. Returns None if a lookup fails.
    """
    if not terms:
        return set()
    hits = set()
    any_term = "fulltext.search:" + "|".join(terms)  # "|" means OR in an OpenAlex filter
    for search, qfilter in queries:
        try:
            for work in discover(session, search, from_date, types,
                                 extra_filter=join_filters(qfilter, any_term), select="id"):
                hits.add(work["id"])
        except RuntimeError as e:
            log.warning("full-text lookup failed: %s", e)
            return None
    return hits


def pdf_text(session, url, max_mb):
    """Download an open-access PDF (size-capped) and return its text, or '' on failure."""
    r = get_with_retry(session, url, stream=True, tries=2)
    if r is None:
        return ""
    buf, limit = io.BytesIO(), max_mb * 1024 * 1024
    for chunk in r.iter_content(65536):
        buf.write(chunk)
        if buf.tell() > limit:
            log.info("PDF over %d MB, skipped: %s", max_mb, url)
            return ""
    try:
        reader = PdfReader(buf)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # malformed PDFs are common; never stop the run for one
        log.info("PDF unreadable (%s): %s", e, url)
        return ""


def screen(db, session, abstracts, rx, cfg, today, fulltext):
    """Abstract first (free); then the OpenAlex full-text flag (no download); then the
    open-access PDF, up to the per-run cap (a cap of 0 means never download PDFs)."""
    pdf_budget = cfg["max_pdf_checks_per_run"]
    pending = db.execute(
        "SELECT id, oa_pdf_url FROM papers WHERE screened = 0 ORDER BY publication_date DESC"
    ).fetchall()
    for pid, pdf_url in pending:
        urls = find_code_urls(abstracts.get(pid, ""), rx)
        source = "abstract" if urls else None
        if not source and fulltext is None:
            continue  # full-text lookup failed; leave unscreened for the next run
        if not source and pid in fulltext:
            source = "fulltext"  # mentioned in the full text; URL not extracted
        if not source and pdf_url and cfg["max_pdf_checks_per_run"] > 0:
            if pdf_budget <= 0:
                continue  # leave unscreened; the next run picks it up
            pdf_budget -= 1
            urls = find_code_urls(pdf_text(session, pdf_url, cfg["max_pdf_mb"]), rx)
            source = "pdf" if urls else None
        db.execute(
            "UPDATE papers SET code_urls = ?, code_source = ?, screened = 1, screened_on = ? WHERE id = ?",
            (" ".join(urls) or None, source, today, pid),
        )
    db.commit()


# ---------------------------------------------------------------- 4. export

def review_regex(terms):
    """Whole words only: 'review' matches 'A Systematic Review' but not 'preview'."""
    if not terms:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b", re.I)


def export(db, out_dir, today, review_columns, review_rx):
    os.makedirs(out_dir, exist_ok=True)
    rows = db.execute(
        "SELECT p.title, p.publication_date, p.venue, p.doi, p.landing_url, p.oa_pdf_url,"
        " p.code_urls, p.code_source, p.queries, p.cited_by,"
        " d.type, d.title, COALESCE(d.doi, d.id), p.duplicate_score"
        " FROM papers p LEFT JOIN papers d ON d.id = p.duplicate_of"
        " WHERE p.screened_on = ? AND p.code_source IS NOT NULL"
        " ORDER BY p.publication_date DESC",
        (today,),
    ).fetchall()
    queue = os.path.join(out_dir, f"review_queue_{today}.csv")
    with open(queue, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title", "date", "venue", "doi", "landing_url", "oa_pdf_url",
                    "code_urls", "code_found_in", "queries", "cited_by", "likely_review",
                    "possible_duplicate_of", "duplicate_score", *review_columns])
        for r in rows:
            # Flags, not filters: the reviewer decides, and nothing is dropped unseen.
            hit = review_rx.search(r[0] or "") if review_rx else None
            dup = f"[{r[10]}] {r[11]} ({r[12]})" if r[11] else ""
            w.writerow([*r[:10], hit.group(0).lower() if hit else "", dup, r[13] or ""])
    # PaperSnitch accepts PDFs and arXiv/landing URLs: one per line, PDF preferred.
    snitch = os.path.join(out_dir, f"papersnitch_inputs_{today}.txt")
    with open(snitch, "w", encoding="utf-8") as f:
        for r in rows:
            f.write((r[5] or r[4] or r[3] or "") + "\n")
    return queue, snitch, len(rows)


# ---------------------------------------------------------------- query check

def check_queries(session, cfg, sample=10):
    """Markdown report for judging each query before a real run (5 requests per query).

    OpenAlex ranks search results by relevance, so precision is best judged by reading the
    top titles *and* titles from deep in the ranking, where off-topic matches pile up.
    """
    since, types = cfg["start_date"], cfg["types"]
    terms = cfg.get("fulltext_terms", [])
    kept = f"from_publication_date:{since},type:{'|'.join(types)}"
    out = [f"# Query check: {cfg.get('title') or 'opentool-watch'}", "",
           f"Papers published since {since}; types kept: {', '.join(types)}.", ""]
    if not os.getenv("OPENALEX_API_KEY"):
        out += ["> No OPENALEX_API_KEY set: OpenAlex may refuse some requests.", ""]

    def titles(results):
        return [f"- {(w.get('publication_date') or '')[:4]} · {w.get('type')} · {w.get('title')}"
                for w in results]

    search_in = cfg.get("search_in", "title_and_abstract")
    out.insert(3, f"Queries are matched against: {search_in.replace('_', ' ')}.")
    for name, query in cfg["queries"].items():
        search, qfilter = query_args(query, search_in)
        q = " ".join(query.split())
        out += [f"## {name}", "", f"`{q}`", ""]
        if "your topic phrase" in q:
            out += ["**This is the template's placeholder query: edit it in the config.**", ""]

        def ask(filters, **params):  # same query, different filters
            params["filter"] = join_filters(qfilter, filters)
            if search:
                params["search"] = search
            return openalex_get(session, params)

        try:
            groups = ask(f"from_publication_date:{since}", group_by="type").get("group_by", [])
            fields = "title,type,publication_date"
            top = ask(kept, **{"per-page": sample, "select": fields, "sort": "relevance_score:desc"})
            n = top.get("meta", {}).get("count", 0)
            code = 0
            if terms and n:
                code = ask(f"{kept},fulltext.search:{'|'.join(terms)}",
                           **{"per-page": 1, "select": "id"}).get("meta", {}).get("count", 0)
            deep_rank = min(int(n * 0.8), 10_000 - sample)  # OpenAlex pages stop at 10,000
            deep = None
            if n > 3 * sample:
                deep = ask(kept, **{"per-page": sample, "page": deep_rank // sample + 1,
                                    "select": fields, "sort": "relevance_score:desc"})
        except RuntimeError as e:
            out += [f"Request failed: {e}", ""]
            continue

        dropped = [(g["key_display_name"], g["count"]) for g in groups
                   if g["key_display_name"] not in types]
        out.append(f"- **{n:,} papers** match with the types kept.")
        if dropped:
            out.append("- Left out by `types`: " + ", ".join(f"{t} {c:,}" for t, c in dropped[:8]) + ".")
        if terms and n:
            out.append(f"- **{code:,}** ({100 * code // n}%) mention a code host in their "
                       "full text: a rough idea of the review queue (abstract links come on top).")
        if n == 0:
            out += ["", "No matches: loosen the query (fewer AND terms, more OR synonyms).", ""]
            continue
        if n > 10_000:
            out.append("- Large: the first run will take a while; consider narrowing the query.")
        out += ["", f"Most relevant {sample}:", *titles(top.get("results", [])), ""]
        if deep:
            out += [f"Around rank {deep_rank:,} (if these are mostly off-topic, tighten the query):",
                    *titles(deep.get("results", [])), ""]
    return "\n".join(out)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--data", default="data")
    ap.add_argument("--since", metavar="YYYY-MM-DD",
                    help="search from this date instead of the last run, e.g. to backfill "
                         "after adding a query or a type to the config")
    ap.add_argument("--check-queries", action="store_true",
                    help="print a report on each query (size, types, code mentions, sample "
                         "titles) and exit, without touching the database")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    session = requests.Session()
    session.headers["User-Agent"] = "opentool-watch/1.0 (" + os.getenv("OPENALEX_MAILTO", "no-mailto") + ")"

    # Built once up front, so a malformed query or setting fails before any request is made.
    search_in = cfg.get("search_in", "title_and_abstract")
    prepared = {name: query_args(q, search_in) for name, q in cfg["queries"].items()}

    if args.check_queries:
        report = check_queries(session, cfg)
        print(report)
        if os.getenv("GITHUB_STEP_SUMMARY"):  # shown on the run's page in GitHub Actions
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(report + "\n")
        return

    os.makedirs(args.data, exist_ok=True)
    db = open_db(os.path.join(args.data, "papers.sqlite"))
    today = dt.date.today().isoformat()

    last = last_run_date(db)
    if args.since:
        since = dt.date.fromisoformat(args.since).isoformat()  # fails early on a bad date
    elif last:
        since = (dt.date.fromisoformat(last) - dt.timedelta(days=cfg["overlap_days"])).isoformat()
    else:
        since = cfg["start_date"]
    log.info("searching %s of papers published since %s", search_in.replace("_", " "), since)

    abstracts, new = {}, 0
    for name, (search, qfilter) in prepared.items():
        n_seen = 0
        for work in discover(session, search, since, cfg["types"], extra_filter=qfilter):
            n_seen += 1
            if upsert(db, work, name, today):
                new += 1
                abstracts[work["id"]] = abstract_text(work.get("abstract_inverted_index"))
        db.commit()
        log.info("query %-12s returned %d papers", name, n_seen)
    log.info("%d new papers after deduplication", new)
    n_dup = flag_duplicates(db, cfg.get("duplicate_similarity", 0.9),
                            cfg.get("duplicate_similarity_same_author", 0.7))
    if n_dup:
        log.info("%d papers look like a preprint/published version of another", n_dup)

    # Full-text lookup covers every unscreened paper, including leftovers from earlier runs.
    oldest = db.execute("SELECT MIN(publication_date) FROM papers WHERE screened = 0").fetchone()[0]
    fulltext = set()
    if oldest:
        fulltext = fulltext_hits(session, list(prepared.values()), cfg.get("fulltext_terms", []),
                                 oldest, cfg["types"])
        if fulltext is not None:
            log.info("%d papers mention a code host in their full text", len(fulltext))

    screen(db, session, abstracts, code_regex(cfg["code_hosts"]), cfg, today, fulltext)
    left = db.execute("SELECT COUNT(*) FROM papers WHERE screened = 0").fetchone()[0]
    if left:
        log.info("%d papers wait for screening in the next run", left)

    db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (today, new))
    db.commit()
    review_columns = cfg.get("review_columns", ["include (y/n)", "notes"])
    review_rx = review_regex(cfg.get("review_title_terms", []))
    out_dir = os.path.join(args.data, "out")
    queue, snitch, n = export(db, out_dir, today, review_columns, review_rx)
    log.info("%d papers with code links screened this run -> %s", n, queue)
    log.info("PaperSnitch input list -> %s", snitch)
    log.info("dashboard -> %s", dashboard.write_dashboard(db, out_dir, cfg, review_rx))


if __name__ == "__main__":
    main()
