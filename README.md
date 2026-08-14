# AI Visibility Reports — GregUniK

Auto-refreshed PeekaBoo AI visibility reports published to GitHub Pages.

**Live reports:** `https://gregunik.github.io/ai-visibility/<client>/`

Index of all reports: https://gregunik.github.io/ai-visibility/tasks/

| Client | URL | Refresh status |
|---|---|---|
| Adelante | https://gregunik.github.io/ai-visibility/adelante/ | ✅ auto |
| Beyond Legal | https://gregunik.github.io/ai-visibility/beyond-legal/ | ✅ auto |
| CoinsBee | https://gregunik.github.io/ai-visibility/coinsbee/ | ⏸ paused — brand deleted from PeekaBoo |
| Credibom | https://gregunik.github.io/ai-visibility/credibom/ | ✅ auto |
| El Corte Inglés (Casa) | https://gregunik.github.io/ai-visibility/elcorteingles-casa/ | ✅ auto |
| El Corte Inglés (Sport) | https://gregunik.github.io/ai-visibility/elcorteingles-sport/ | ✅ auto |
| ERA Imobiliária | https://gregunik.github.io/ai-visibility/era/ | ✅ auto |
| Leroy Merlin | https://gregunik.github.io/ai-visibility/leroymerlin/ | ⏸ paused — Analytics1 account deleted |
| REDUNIQ | https://gregunik.github.io/ai-visibility/reduniq/ | ✅ auto |
| The Tool Ranch | https://gregunik.github.io/ai-visibility/toolranch/ | ✅ auto |
| UniK SEO | https://gregunik.github.io/ai-visibility/unikseo/ | ✅ auto |
| Visitmadeira | https://gregunik.github.io/ai-visibility/visitmadeira/ | ⏸ paused — brand deleted from PeekaBoo |
| Vortal (Portugal) | https://gregunik.github.io/ai-visibility/vortal-pt/ | ✅ auto |
| Vortal (España) | https://gregunik.github.io/ai-visibility/vortal-es/ | ✅ auto |
| WiZink (Portugal) | https://gregunik.github.io/ai-visibility/wizink-pt/ | ✅ auto |
| WiZink (España) | https://gregunik.github.io/ai-visibility/wizink-es/ | ✅ auto |
| XTB | https://gregunik.github.io/ai-visibility/xtb/ | ✅ auto |

Status as of 2026-08-02 — all 12 active clients building green. A ⚠️ client keeps serving its last good report; the run goes red until it's fixed.

---

## How it works

- **Schedule:** auto-refreshes every Monday + Thursday at 8am UTC
- **Template:** always cloned fresh from https://github.com/filipelinsduarte/ai-visibility-report — any upstream layout update is picked up automatically
- **Zero LLM tokens:** NLP and action generation are disabled (`skip_nlp: true`). Only PeekaBoo API calls are made.

---

## Manually refresh data

Go to **Actions → Refresh AI Visibility Reports → Run workflow**

https://github.com/GregUniK/ai-visibility/actions/workflows/refresh.yml

---

## Add a new client

1. Create `configs/<slug>.json` with the brand info (see existing files as reference):
```json
{
  "brands": [
    {
      "id": "<uuid-from-peekaboo-dashboard>",
      "name": "Brand Name",
      "key": "brandkey",
      "domain": "brand.com"
    }
  ],
  "output_file": "<slug>-report.html"
}
```
If the brand is under a non-default PeekaBoo account, add `"api_key_env": "AIPEEKABOO_API_KEY_XXX"` and set that secret in GitHub.

2. Create `stubs/<slug>.json` containing just `[]`

3. Commit and push — the next workflow run picks it up automatically.

The report will be live at `https://gregunik.github.io/ai-visibility/<slug>/`

---

## Remove a client

Delete `configs/<slug>.json`, commit and push. The next run skips that client. The existing `<slug>/index.html` stays in the repo until you manually delete it.

---

## Pause a client (keep the report, stop building it)

Add `"paused": true` and a `"paused_reason"` to `configs/<slug>.json`:
```json
{
  "paused": true,
  "paused_reason": "Brand deleted from PeekaBoo (API 404, confirmed 2026-07-17).",
  "brands": [ ... ]
}
```
The client is skipped at build time and **does not count as a failure**, so the run stays green. The published `<slug>/index.html` is left untouched and keeps serving its last good data.

Use this when a brand disappears from PeekaBoo but the report should stay online. Without it, the client fails on every run and the red build stops meaning anything.

---

## Add a brand to an existing report (multi-brand)

Add another object to the `brands` array in the config. Example — El Corte Inglés has two brands (Casa + Sports) in one report:
```json
{
  "brands": [
    { "id": "8fd9c9fe-...", "name": "El Corte Inglés (Casa)", "key": "elcorteingles_casa", "domain": "elcorteingles.pt" },
    { "id": "b2172ee8-...", "name": "El Corte Inglés", "key": "elcorteingles", "domain": "elcorteingles.pt" }
  ]
}
```

---

## PeekaBoo accounts & GitHub secrets

Three PeekaBoo accounts are in use. Secrets are stored in:
**https://github.com/GregUniK/ai-visibility/settings/secrets/actions**

| Secret name | Account | Used by |
|---|---|---|
| `AIPEEKABOO_API_KEY` | analytics@unik-seo.com (main) | coinsbee*, credibom, era, reduniq, unikseo, visitmadeira*, wizink-pt, wizink-es, xtb |
| `AIPEEKABOO_API_KEY_ECI` | Analytics2 | elcorteingles-casa, elcorteingles-sport |
| `AIPEEKABOO_API_KEY_LM` | Analytics1 — **account deleted 2026-07** | leroymerlin* |

\* paused — see the status table at the top.

`build_all.py` prints every brand each key can actually see, with ids, at the start of
every run. Read that block first when a client starts failing:
```
AIPEEKABOO_API_KEY_ECI: 2 brand(s)
    8fd9c9fe-20d3-4e7c-a8bb-9523ff1308fb  El Corte Inglés (Casa)
    b2172ee8-0472-43b2-9b0c-7b575a6061bb  El Corte Inglés
AIPEEKABOO_API_KEY_LM: HTTP 403 — Forbidden
```
Triage:
- **`HTTP 403` on a key** → key or its subscription/account is dead. Account-side fix.
- **Brand absent from the list** → deleted from PeekaBoo. Pause the client.
- **Brand listed with the same id as the config, but the build still 404s on it** →
  the build used the *wrong key*, not a bad id. On a failure, build_all.py's
  `diagnose()` re-hits `/prompts` with the resolved key: if that probe returns 200
  while the build 404'd, the build sent a different key. See the note below.

> **Non-main accounts and the `AIPEEKABOO_API_KEY` override.** build_fast.py's
> `load_config()` overrides the config's api key with the `AIPEEKABOO_API_KEY` env var
> whenever it is set. build_all.py works around this by setting that env var, per
> subprocess, to each client's resolved key. If a non-main client (ECI, or a future
> `_LM`) suddenly 404s across the board after an upstream template change, check that
> this per-client env override in build_all.py is still in place — losing it makes
> every client build with the main key, so only non-main accounts break.

A brand's id is also visible in its share link: open the share URL and the `brandId`
is in the page source (`GET /brands` with the key is the more direct route).

To find brand UUIDs: open the brand in the PeekaBoo dashboard — the UUID is in the URL. Or call `GET https://www.aipeekaboo.com/api/v1/brands` with `X-API-Key: pk_...`

---

## Repo structure

```
configs/          ← one JSON per client (no API keys stored here)
stubs/            ← empty [] files, one per client (skip LLM action generation)
<slug>/           ← built HTML reports committed here, served via GitHub Pages
.github/
  workflows/
    refresh.yml   ← scheduled + manual trigger
  scripts/
    build_all.py  ← auto-discovers clients from configs/, patches upstream build tool
```
