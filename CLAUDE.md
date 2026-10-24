# opentool-watch

Topic-agnostic, periodic discovery of papers from OpenAlex with a pre-screen for released code
or weights. A topic is defined entirely by a YAML config; `examples/ldct/config.yaml` (AI for
low-dose chest CT) is the reference use case. Results feed human-curated catalogues, so
accuracy matters more than coverage.

## How it works

`pipeline.py` runs four stages in order:

1. **discover** – queries the OpenAlex API (`/works`) for each search in the config, following
   the cursor until the last page, filtered by publication date and `types`.
2. **dedup** – stores each paper once in `<data>/papers.sqlite`, keyed on the OpenAlex ID.
   The `runs` table records run dates; later runs search only from the last run date minus
   `overlap_days` (or from `--since`). `flag_duplicates` then links preprints to separate
   published versions by title similarity and first author (`duplicate_of`); never merge.
3. **screen** – looks for code or weights links (`code_hosts`) in the abstract; otherwise flags
   papers whose full text mentions a `fulltext_terms` word, using OpenAlex `fulltext.search`
   (no download, no URL: `code_source = 'fulltext'`). Downloading open-access PDFs is optional
   and off by default (`max_pdf_checks_per_run: 0`).
4. **export** – writes `<data>/out/review_queue_<date>.csv` (with the config's
   `review_columns`) and `<data>/out/papersnitch_inputs_<date>.txt` for papers screened in
   that run. `dashboard.py` then rebuilds `<data>/out/dashboard.html` from the whole
   database: a single offline page (stdlib only, no CDN), data embedded as JSON and rendered
   with plain JS. Insert data with `textContent` and only link http(s) URLs: titles and URLs
   come from an external API.

Discovery uses OpenAlex only. This is a decision, not a gap: do not add other sources
(PubMed, arXiv, paperscraper, Semantic Scholar) unless asked.

## Commands

```bash
docker build -t opentool-watch .
docker run --rm -v ~/opentool-watch-data:/data -e OPENALEX_MAILTO=<email> -e OPENALEX_API_KEY=<key> \
  opentool-watch --config /app/examples/ldct/config.yaml
python pipeline.py --config examples/ldct/config.yaml --data ./data   # without Docker
```

## Distribution

- `--check-queries` prints a Markdown report per query (5 OpenAlex requests each) and exits
  without touching the database; in GitHub Actions it also goes to the run's summary page.
- `.github/workflows/watch.yml` runs the tool monthly in a user's copy of the repo, commits
  `watch-data/` (database and queues, `git add -f` because `*.sqlite` is ignored) and deploys
  the dashboard to GitHub Pages. It is off unless the repo variable `WATCH_ENABLED` is `true`.
- `.github/workflows/docker-publish.yml` publishes `ghcr.io/<owner>/opentool-watch` for every
  `v*` tag. To release: update the version in the README examples if needed, then
  `git tag v0.X.Y && git push origin v0.X.Y`.
- Lint workflow changes with actionlint before pushing.

## Rules

- **Keep the code topic-agnostic.** Queries, code hosts, full-text terms and review columns
  live in the config, never in `pipeline.py`. Topic-specific material goes under `examples/`.
- **Never delete or recreate `papers.sqlite`.** It is the dedup record and the run history.
  Schema changes must be additive (`ALTER TABLE ... ADD COLUMN`), applied in `open_db`.
- **Never invent metadata.** If a field (weights, licence, training data, code link) cannot be
  found in the source, leave it empty or write "not stated". Do not infer it from the title.
- Keep OpenAlex requests polite: `mailto` parameter, `select` to limit fields, backoff on
  429/5xx, a short sleep between pages.
- Never commit e-mail addresses or API keys. They come from environment variables
  (`OPENALEX_MAILTO`, and `OPENALEX_API_KEY`, required by OpenAlex since Feb 2026).
- One bad paper or PDF must never stop a run: log it and continue.
- Keep dependencies minimal (requests, PyYAML, pypdf) and pinned in `requirements.txt`.

## Testing

The sandbox may not reach OpenAlex. Test logic offline by replacing `fetch_page` (both normal
and `fulltext.search` calls) and `pdf_text` with functions returning fixture data, then run
`main()` twice against a temporary data folder. Check: papers found by several queries are
stored once with all query names; the second run reports 0 new papers; the review queue lists
only papers with a code signal; a failed full-text lookup leaves papers unscreened.
For schema changes, also start from a database built with the old schema and check it is
upgraded in place. Keep `flag_duplicates` fast at first-harvest size (a few thousand papers).
Before changing a query, compare `meta.count` and the precision of a sample of results
(top page and a late page) against the current query.

## Open decisions

- **Reproducibility score.** Optional, for a final shortlist only. PaperSnitch is run manually
  on `papersnitch_inputs_<date>.txt`; it has no documented API. Do not integrate a scorer
  unless asked.
- **Coverage gap.** Papers without a code link in the abstract and without full text in
  OpenAlex cannot be screened. `fulltext` hits can be false positives; human review decides.
