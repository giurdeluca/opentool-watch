# opentool-watch

Monthly discovery of papers on any research topic from [OpenAlex](https://openalex.org), with a
pre-screen for released code or model weights. You describe the topic with OpenAlex search
queries in a YAML file; the tool keeps a deduplicated record of every paper it has seen and,
each run, writes a review queue of new papers that point to GitHub, Hugging Face, Zenodo, etc.

No PDFs are downloaded by default: code links are taken from the abstract, and otherwise
OpenAlex's own full-text search flags papers that mention a code host.

Use case included: open AI tools for low-dose chest CT (lung cancer screening and incidental
findings), in [`examples/ldct/config.yaml`](examples/ldct/config.yaml).

## Requirements

- Docker (or Python 3.12 with `pip install -r requirements.txt`)
- A free OpenAlex API key (https://openalex.org/settings/api), required since February 2026

## Quick start

```bash
git clone https://github.com/<you>/opentool-watch.git && cd opentool-watch
docker build -t opentool-watch .
mkdir -p ~/opentool-watch-data
docker run --rm -v ~/opentool-watch-data:/data \
  -e OPENALEX_MAILTO=you@example.org -e OPENALEX_API_KEY=your-key \
  opentool-watch --config /app/examples/ldct/config.yaml
```

Without Docker: `python pipeline.py --config examples/ldct/config.yaml --data ./data`.

To keep the key out of your shell history and crontab, put both variables in a file readable
only by you (`chmod 600`) and pass `--env-file that-file` instead of the two `-e` flags.

## Your own topic

Copy `config.yaml` (a commented template), replace the queries, and either rebuild the image
or mount the file: `-v $PWD/my-topic.yaml:/app/config.yaml:ro`. Everything that defines a topic
lives in the config:

| key | meaning |
|---|---|
| `queries` | named OpenAlex search strings (Boolean, quoted phrases) |
| `start_date`, `overlap_days` | first-run horizon; safety overlap for later runs |
| `types` | OpenAlex work types to keep |
| `code_hosts` | domains whose links count as "code or weights available" |
| `fulltext_terms` | words looked up in OpenAlex full text when the abstract has no link |
| `max_pdf_checks_per_run` | optional PDF download screening (0 = off) |
| `review_columns` | empty decision columns added to the review queue |

Before relying on a query, check its precision: look at `meta.count` and a sample of results
from the first page and a late page.

## Schedule (host cron, 1st of each month at 06:00)

```cron
0 6 1 * * docker run --rm -v $HOME/opentool-watch-data:/data --env-file $HOME/opentool-watch-data/.env opentool-watch --config /app/examples/ldct/config.yaml >> $HOME/opentool-watch-data/cron.log 2>&1
```

The first run harvests everything since `start_date`. If the log says "papers wait for
screening" (a full-text lookup failed, or PDF screening is on and its cap was reached), run it
again; later runs only fetch papers published since the previous run.

## Outputs (in the data folder)

- `papers.sqlite` – every paper ever seen (the dedup record and run history). Do not delete it.
- `out/review_queue_<date>.csv` – papers screened in that run that have a code signal, with
  empty `review_columns` for your decisions. `code_found_in` is `abstract`, `pdf` (with the
  URL) or `fulltext` (the full text mentions a code host, but the URL was not extracted: find
  it in the paper while reviewing).
- `out/papersnitch_inputs_<date>.txt` – one PDF or landing URL per line, ready for an optional
  reproducibility assessment with PaperSnitch or similar tools.

## Limitations

- Discovery uses OpenAlex only.
- Papers with no code link in the abstract and no full text in OpenAlex cannot be screened.
- `fulltext` hits can be false positives (e.g. a Zenodo dataset rather than code, or a GitHub
  link in the references). The review queue is a starting point for human review, not a verdict.

## License

MIT, see [LICENSE](LICENSE).
