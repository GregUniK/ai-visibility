# Labs: the builder and its preview

`labs/tools/` holds the builder (`build_labs.py`), the page template (`template.html`) and
the tests. The same code builds two editions:

- **Live** — `python labs/tools/build_labs.py --live --all`: `configs/<slug>.json` →
  `<slug>/index.html`, served at `https://gregunik.github.io/ai-visibility/<slug>/`.
  Run by `refresh.yml`, Monday + Thursday.
- **Labs** — `python labs/tools/build_labs.py --all`: `labs/configs/<slug>.json` →
  `labs/<slug>/index.html`, served at `https://gregunik.github.io/ai-visibility/labs/<slug>/`
  with a "Labs" badge and `noindex`. Run by `labs.yml` on every push that changes
  `labs/tools/`, `labs/configs/` or the workflow. Only Credibom is configured, so a builder
  change shows up on its labs page within minutes, at about 100 API calls. The other labs
  URLs redirect to the live reports.

## Try a change on every client before it goes live

Push the change to a branch and run **Refresh AI Visibility Reports** on that branch
(Actions → Run workflow → pick the branch). It builds every client's live page and commits
the pages to that branch, not to `main`, so nothing public changes; check them, then merge.
A full build is about 1,070 calls on the main account and 1,014 on the El Corte Inglés one;
the main account allows about 2,000 a day, so don't run it on the same day as a refresh.

## What the reports show

- **Visibility scores** (last 90 days): visibility score, share of voice, rank vs tracked
  competitors (a brand no AI named says "Not named"), score per AI, and a score-per-run chart
  for the brand and each tracked competitor.
- **Tracked competitors** split from every other name the AIs mention (regulators,
  comparison sites, other banks). The brand's own name variants are not counted as competitors.
- **Fan-out searches**: the web searches ChatGPT and Gemini ran while answering each prompt
  (`GET /brands/:id/prompts/:promptId/fanout-queries`): themes, brands named in searches,
  sites searched directly, categories, and the searches inside each prompt's row.
- **"Missing, competitors named"** filter on the Prompts tab.
- **Data notes**: inactive prompts left out, runs where a model is missing or short,
  prompts at the 100-run history cap, endpoints that failed during the build.

## Add a client

Live: add `configs/<slug>.json` (see the main README). Labs: copy it into
`labs/configs/<slug>.json`. For a brand under another API account, set `"api_key_env"` to
`AIV_API_KEY_ECI` or `AIV_API_KEY_LM` (both workflows map them).

## Build locally without a key

`python labs/tools/build_labs.py --config labs/configs/credibom.json --fixtures DIR --out FILE`
reads saved API responses from `DIR` (`prompts.json`, `prompt-<id>.json`,
`fanout-<id>.json`, `visibility.json`, `by-model.json`, `competitors.json`,
`timeseries.json`, `snapshot.json`). Add `--live` for the live edition.

Tests: `python -m pytest labs/tools -p no:cacheprovider`
