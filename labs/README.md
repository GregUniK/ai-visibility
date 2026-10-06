# Labs: test version of the AI visibility reports

Live reports stay at `https://gregunik.github.io/ai-visibility/<slug>/` and are built
exactly as before (`configs/`, `.github/scripts/build_all.py`, `refresh.yml`). Labs
builds a second copy with new data, at:

`https://gregunik.github.io/ai-visibility/labs/<slug>/`

Nothing links to it and it is `noindex`. When a labs change is approved, it can be
moved to production on its own.

## What labs adds

- **Visibility scores** (last 90 days): visibility score, share of voice, rank vs
  tracked competitors, score per AI, and a score-per-run chart for the brand and
  each tracked competitor.
- **Tracked competitors** split from every other name the AIs mention (regulators,
  comparison sites, other banks). The brand's own name variants are no longer
  counted as competitors.
- **Fan-out searches**: the web searches ChatGPT and Gemini ran while answering each
  prompt (`GET /brands/:id/prompts/:promptId/fanout-queries`). New tab plus the
  searches inside each prompt's row.
- **"Missing, competitors named"** filter on the Prompts tab.
- **Data notes**: inactive prompts left out, runs where a model is missing, prompts
  at the 100-run history cap, endpoints that failed during the build.
- Fixes: inactive prompts are no longer counted; each model's "latest result" is its
  newest run (upstream used the oldest).

## Add a client

Copy its production config into `labs/configs/<slug>.json` (drop `output_file`).
For a brand under another API account, set `"api_key_env"` to `AIV_API_KEY_ECI` or
`AIV_API_KEY_LM` (see `labs.yml`). Push: the labs workflow builds it. Each build
makes about two API calls per prompt plus six, so mind the daily API allowance for
brands with hundreds of prompts (production uses about one per prompt, Mon and Thu
around 08:00 UTC, on the same keys).

## Rebuild

Actions → **Build labs reports** → Run workflow. It also runs on any push that
changes `labs/tools/`, `labs/configs/` or the workflow.

## Build locally without a key

`python labs/tools/build_labs.py --config labs/configs/credibom.json --fixtures DIR --out FILE`
reads saved API responses from `DIR` (`prompts.json`, `prompt-<id>.json`,
`fanout-<id>.json`, `visibility.json`, `by-model.json`, `competitors.json`,
`timeseries.json`, `snapshot.json`).

Tests: `python -m pytest labs/tools -p no:cacheprovider`
