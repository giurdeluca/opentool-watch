# opentool-watch

Monthly discovery of papers on any research topic from [OpenAlex](https://openalex.org), with a
pre-screen for released code or model weights. You describe the topic with OpenAlex search
queries in a YAML file; the tool keeps a deduplicated record of every paper it has seen and,
each run, writes a review queue of new papers that point to GitHub, Hugging Face, Zenodo, etc.

No PDFs are downloaded by default: code links are taken from the abstract, and otherwise
OpenAlex's own full-text search flags papers that mention a code host.

Use case included: open AI tools for low-dose chest CT (lung cancer screening and incidental
findings), in [`examples/ldct/config.yaml`](examples/ldct/config.yaml) --- see the dashboard demo here: https://giurdeluca.github.io/opentool-watch/

> **Read before relying on the results.** The screening has not been validated against manual
> labels, and a "code signal" means that a paper points to a code host, not that it introduces
> a new tool. The output is a queue for human review, not a curated list. See
> [Accuracy and scope](#accuracy-and-scope).

## Three ways to run it

All three need a free OpenAlex API key (https://openalex.org/settings/api), required by
OpenAlex since February 2026.

### 1. On GitHub, with no installation

GitHub runs the tool every month in your own copy of this repository, keeps the results there,
and publishes the dashboard as a web page.

1. **Make your copy**: click **Use this template** (or **Fork**) at the top of this page.
2. **Add your key** in your copy, under *Settings → Secrets and variables → Actions*:
   - *Secrets* tab: `OPENALEX_API_KEY` = your key (and optionally `OPENALEX_MAILTO` = your e-mail);
   - *Variables* tab: `WATCH_ENABLED` = `true`, and `WATCH_PAGES` = `true` to publish the dashboard.
3. **Turn on the dashboard site**: *Settings → Pages → Source*: **GitHub Actions**.
4. **Describe your topic**: edit `config.yaml` in the browser (pencil icon): set `title` and
   replace the placeholder query. To use another file, e.g. the LDCT example, set the variable
   `WATCH_CONFIG` = `examples/ldct/config.yaml`.
5. **Check the queries**: *Actions → Watch → Run workflow*, mode **check**. The report (size,
   types, code mentions, sample titles) appears on the run's summary page. Edit and repeat until
   the sample titles look right (see [Checking your queries](#checking-your-queries)).
6. **Start**: run the workflow again with mode **run**. The first run harvests everything since
   `start_date`; the dashboard then appears at `https://<your-user>.github.io/<repository>/`,
   and the review queues in `watch-data/out/` of your repository.

If you already have a personal site at `<your-user>.github.io`, the dashboard is added under
it at `/<repository>/` and the rest of your site is not affected. GitHub Pages needs a public
repository on a free account; with a private one, leave `WATCH_PAGES` unset and download
`watch-data/out/dashboard.html` from the repository instead.

After that it runs by itself at 06:00 UTC on the 1st of every month. To backfill after adding a
query or a type, run it by hand with **since** set to your `start_date`.

Everything the tool produces (database, review queues, dashboard) is committed to your
repository, and the GitHub Pages site is public. The data are public OpenAlex metadata, but your
decisions in the review columns are yours to keep elsewhere if they should stay private.

### 2. With Docker

A ready-made image is published for each release, so nothing needs building:

```bash
mkdir -p ~/opentool-watch-data
printf 'OPENALEX_API_KEY=your-key\nOPENALEX_MAILTO=you@example.org\n' > ~/opentool-watch-data/.env
chmod 600 ~/opentool-watch-data/.env    # readable only by you
docker run --rm -v ~/opentool-watch-data:/data --env-file ~/opentool-watch-data/.env \
  ghcr.io/giurdeluca/opentool-watch --config /app/examples/ldct/config.yaml
```

For your own topic, mount your config: add `-v $PWD/my-topic.yaml:/my-topic.yaml:ro` and use
`--config /my-topic.yaml`. Pin a version (e.g. `ghcr.io/giurdeluca/opentool-watch:0.1.0`) to
keep results reproducible; to build the image yourself instead: `docker build -t opentool-watch .`.

Monthly, with host cron (1st of each month at 06:00):

```cron
0 6 1 * * docker run --rm -v $HOME/opentool-watch-data:/data --env-file $HOME/opentool-watch-data/.env ghcr.io/giurdeluca/opentool-watch --config /app/examples/ldct/config.yaml >> $HOME/opentool-watch-data/cron.log 2>&1
```

### 3. With Python

```bash
git clone https://github.com/giurdeluca/opentool-watch.git && cd opentool-watch
pip install -r requirements.txt
export OPENALEX_API_KEY=your-key OPENALEX_MAILTO=you@example.org
python pipeline.py --config examples/ldct/config.yaml --data ./data
```

The first run harvests everything since `start_date`; later runs only fetch papers published
since the previous run. If the log says "papers wait for screening" (a full-text lookup failed,
or PDF screening is on and its cap was reached), run it again.

## Your own topic

Start from `config.yaml`, a commented template. Everything that defines a topic lives in it:

| key | meaning |
|---|---|
| `title` | heading of the dashboard |
| `queries` | named OpenAlex search strings (Boolean, quoted phrases) |
| `search_in` | `title_and_abstract` (default, precise) or `all_text` (also full text: more recall, many off-topic papers) |
| `start_date`, `overlap_days` | first-run horizon; safety overlap for later runs |
| `types` | OpenAlex work types to keep |
| `code_hosts` | domains whose links count as "code or weights available" |
| `fulltext_terms` | words looked up in OpenAlex full text when the abstract has no link |
| `max_pdf_checks_per_run` | optional PDF download screening (0 = off) |
| `review_title_terms` | title words that flag a paper as `likely_review` (flagged, not dropped) |
| `duplicate_similarity`, `duplicate_similarity_same_author` | title-similarity thresholds for flagging a preprint/published pair |
| `review_columns` | empty decision columns added to the review queue |

Later runs only look back to the previous run, so after adding a query or a type, backfill
once with `--since <start_date>`. Papers already in the database are not duplicated.

### Checking your queries

Before the first real run, check each query without touching the database:

```bash
python pipeline.py --config my-topic.yaml --check-queries
# Docker: docker run --rm --env-file ... ghcr.io/giurdeluca/opentool-watch --config /my-topic.yaml --check-queries
# GitHub: Actions -> Watch -> Run workflow, mode "check"
```

For each query it reports how many papers match, which publication types `types` leaves out,
how many papers mention a code host in their full text, and two samples of titles: the most
relevant ones and some from deep in the results (around 80% of the ranking). OpenAlex sorts by
relevance, so the deep sample is where off-topic matches show up: if most of those titles are
off-topic, tighten the query (more specific phrases, an extra `AND` group). With the default
`search_in: title_and_abstract`, a paper only matches if its title or abstract uses your words,
so add synonyms (e.g. `"neural network"` or `convolutional` next to `"deep learning"`) and
watch how the count changes. A check costs five
OpenAlex requests per query.

## Outputs (in the data folder)

- `papers.sqlite` – every paper ever seen (the dedup record and run history). Do not delete it.
- `out/review_queue_<date>.csv` – papers screened in that run that have a code signal, with
  empty `review_columns` for your decisions. `code_found_in` is `abstract`, `pdf` (with the
  URL) or `fulltext` (the full text mentions a code host, but the URL was not extracted: find
  it in the paper while reviewing). `likely_review` shows the title word that suggests a
  review article; OpenAlex's own `review` type is excluded by `types` already.
  `possible_duplicate_of` names the preprint (or published version) of the same paper when
  OpenAlex keeps them as separate works, with its title similarity in `duplicate_score`.
  Pairs are matched on title, plus first author for weaker matches, and never merged.
- `out/dashboard.html` – every paper tracked so far, in one page that opens offline in any
  browser: summary numbers, papers per year with and without a code signal, where the signal
  was found, per query and per type, and a filterable, sortable table with links to verify each
  paper (DOI, publisher page, open-access PDF, OpenAlex record, code links). Rebuilt at the end
  of every run; to rebuild it from an existing database without querying OpenAlex:
  `python dashboard.py --config <config> --data <data folder>` (Docker:
  `docker run --rm -v <data>:/data --entrypoint python ghcr.io/giurdeluca/opentool-watch dashboard.py --config /app/examples/ldct/config.yaml --data /data`).
- `out/papersnitch_inputs_<date>.txt` – one PDF or landing URL per line, ready for an optional
  reproducibility assessment with [PaperSnitch](#optional-reproducibility-assessment-with-papersnitch).

## Optional: reproducibility assessment with PaperSnitch

opentool-watch only tells you that a paper *points to* code. Whether that code is usable is a
separate question, which [PaperSnitch](https://github.com/AImageLab-zip/paper-snitch)
(AImageLab, University of Modena and Reggio Emilia) is designed to answer. It parses a paper,
checks that the linked repository exists and contains real code, and evaluates paper and
repository against reproducibility checklists, producing a verifiability score with
sub-scores and evidence excerpts to inspect. It never executes the code. It is described in:

> F. Bolelli, D. Santoli, K. Marchesini, L. Lumetti, C. Grana. *The Paper Has a GitHub, the
> GitHub Has a README, the README Has Nothing: Reproducibility Signals for Review Support.*
> MICCAI 2026. [Paper page](https://papers.miccai.org/miccai-2026/1055-Paper0729.html)

PaperSnitch is not bundled or called by this tool. A practical workflow is to review the
queue, shortlist the papers you plan to include, and run PaperSnitch on those entries of
`papersnitch_inputs_<date>.txt`; see its repository for installation and requirements.

## Related tools

No existing tool we found combines topic monitoring with a code pre-screen for clinical
literature, but several cover parts of it and are worth knowing:

| kind | examples | difference from opentool-watch |
|---|---|---|
| Detecting open code/data statements in papers | [ODDPub](https://github.com/quest-bih/oddpub), [rtransparent](https://github.com/serghiou/rtransparent), SciScore, SoftCite | Classify full texts you already have (PDF or PubMed Central XML); they do not discover or monitor papers. ODDPub has published accuracy figures: open-code sensitivity 0.73 in its original validation on biomedical papers, and 0.60 when re-validated on arXiv preprints ([Collins & Alexander](https://arxiv.org/abs/2107.10724)); see also a [comparison of these tools](https://arxiv.org/abs/2507.17991) (Eckmann et al.). |
| Linking papers to code | Papers with Code (closed in July 2025; data dumps archived), Hugging Face Papers, CatalyzeX, [RepoFromPaper](https://oa.upm.es/82930/) | Centred on machine-learning preprints and conferences; little coverage of clinical journals. RepoFromPaper is a research method that needs the full text. |
| Literature monitoring | OpenAlex email/RSS alerts, [paperscreen](https://github.com/akcelenk/paperscreen) | Deliver new papers on a topic; paperscreen learns to rank them from your judgements. Neither checks for released code or weights. |
| Curated model catalogues (medical imaging) | [MHub.ai](https://mhub.ai), [Grand Challenge algorithms](https://grand-challenge.org/algorithms/), [MONAI Model Zoo](https://monai.io/model-zoo.html) | Curated, runnable models. opentool-watch can feed such a catalogue rather than replace it. |
| Reproducibility assessment | [PaperSnitch](https://github.com/AImageLab-zip/paper-snitch) | Assesses papers you already selected; it sits downstream of this tool (see above). |

If you use the code-statement detectors above, they can complement this tool on the papers
whose full text you have.

## Accuracy and scope

**Accuracy has not been validated.** The precision and recall of the code pre-screen, the
`likely_review` flag and the `possible_duplicate_of` flag have not been measured against manual
labels, for any topic. Thresholds and word lists are reasonable defaults, not tuned values.
Before reporting numbers produced with this tool (e.g. "N open tools were found"), check it on
your own topic, for example:

- **precision**: label a random sample of the review queue (does the paper really link to its
  code or weights?), separately for `abstract` and `fulltext` hits;
- **missed papers**: label a random sample of papers *without* a code signal (`out/dashboard.html`,
  code signal "No code signal"), to estimate how many releases the screen misses;
- **flags**: check the `possible_duplicate_of` pairs and `likely_review` titles in the same samples.

**A code signal is broader than "this paper introduces a tool".** It only means that the
abstract or full text points to a code host. Besides papers that develop and release a new
model, the queue will contain, for example:

- validation or clinical studies of an existing tool, linking that tool's repository;
- papers that share analysis scripts or statistics code, not a reusable tool;
- dataset, benchmark or challenge papers (e.g. Zenodo or Grand Challenge links);
- reviews and surveys that list repositories;
- `fulltext` hits where the code host appears only in the references or related work.

Deciding whether a paper introduces a tool, and whether its code or weights are actually
usable, is the reviewer's job (the `review_columns`), possibly helped by PaperSnitch.

## Limitations

- Discovery uses OpenAlex only, and is only as good as the search queries: papers not matched
  by any query are never seen. With `search_in: title_and_abstract`, a relevant paper whose
  title and abstract use other words than the query (e.g. "CNN" instead of "deep learning")
  is missed.
- Papers with no code link in the abstract and no full text in OpenAlex cannot be screened;
  code released after publication, or announced only on a project page, is missed.
- Reviews typed as `article` are flagged by title words only; duplicates are matched by title
  similarity and first author, so a preprint whose title changed completely is not linked.

## License

MIT, see [LICENSE](LICENSE).
