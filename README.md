# AI Visibility Reports — GregUniK

Auto-refreshed AI visibility reports published to GitHub Pages.

**Live reports:** `https://gregunik.github.io/ai-visibility/<client>/`

Index of all reports: https://gregunik.github.io/ai-visibility/tasks/

| Client | URL | Refresh status |
|---|---|---|
| Adelante | https://gregunik.github.io/ai-visibility/adelante/ | ✅ auto |
| Beyond Legal | https://gregunik.github.io/ai-visibility/beyond-legal/ | ✅ auto |
| CoinsBee | https://gregunik.github.io/ai-visibility/coinsbee/ | ⏸ paused — brand deleted from the tracking platform |
| Credibom | https://gregunik.github.io/ai-visibility/credibom/ | ✅ auto |
| El Corte Inglés (Casa) | https://gregunik.github.io/ai-visibility/elcorteingles-casa/ | ✅ auto |
| El Corte Inglés (Sport) | https://gregunik.github.io/ai-visibility/elcorteingles-sport/ | ✅ auto |
| ERA Imobiliária | https://gregunik.github.io/ai-visibility/era/ | ✅ auto |
| Leroy Merlin | https://gregunik.github.io/ai-visibility/leroymerlin/ | ⏸ paused — Analytics1 account deleted |
| REDUNIQ | https://gregunik.github.io/ai-visibility/reduniq/ | ✅ auto |
| The Tool Ranch | https://gregunik.github.io/ai-visibility/toolranch/ | ✅ auto |
| UniK SEO | https://gregunik.github.io/ai-visibility/unikseo/ | ✅ auto |
| Visitmadeira | https://gregunik.github.io/ai-visibility/visitmadeira/ | ⏸ paused — brand deleted from the tracking platform |
| Vortal (Portugal) | https://gregunik.github.io/ai-visibility/vortal-pt/ | ✅ auto |
| Vortal (España) | https://gregunik.github.io/ai-visibility/vortal-es/ | ✅ auto |
| WiZink (Portugal) | https://gregunik.github.io/ai-visibility/wizink-pt/ | ✅ auto |
| WiZink (España) | https://gregunik.github.io/ai-visibility/wizink-es/ | ✅ auto |
| XTB | https://gregunik.github.io/ai-visibility/xtb/ | ✅ auto |

A failing client keeps serving its last good report; the run goes red and opens an issue until it's fixed.

---

## How it works

- **Schedule:** `.github/workflows/refresh.yml` rebuilds every Monday + Thursday at 8am UTC.
- **Builder:** `labs/tools/build_labs.py --live --all` with `labs/tools/template.html`, our own
  code (no template cloned from elsewhere). Tabs: Overview (with the official visibility scores),
  Prompts, Fan-out searches, Sentiment, Competitors, Citations, plus data notes.
- **Zero LLM tokens:** only tracking-API calls. A full refresh is about 1,070 calls on the main
  account and 1,014 on the El Corte Inglés account; the main account allows about 2,000 a day.
- **Labs** (`labs/`, see `labs/README.md`) is the preview: a change to the builder rebuilds the
  Credibom labs page at /ai-visibility/labs/credibom/ straight away; the live reports pick it up
  at the next refresh. To check every client before merging, run `labs.yml` on the PR branch.

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
      "id": "<brand-uuid-from-the-tracking-dashboard>",
      "name": "Brand Name",
      "key": "brandkey",
      "domain": "brand.com"
    }
  ]
}
```
If the brand is under a non-default tracking account, add `"api_key_env": "AIV_API_KEY_XXX"`, add
that secret in GitHub and map it in the `Build all clients` step of `refresh.yml`.

2. Commit and push — the next run picks it up. The report goes live at
`https://gregunik.github.io/ai-visibility/<slug>/`; add a card to `tasks/index.html` once it is.

---

## Remove a client

Delete `configs/<slug>.json`, commit and push. The next run skips that client. The existing `<slug>/index.html` stays in the repo until you manually delete it.

---

## Pause a client (keep the report, stop building it)

Add `"paused": true` and a `"paused_reason"` to `configs/<slug>.json`:
```json
{
  "paused": true,
  "paused_reason": "Brand deleted from the tracking platform (API 404, confirmed 2026-07-17).",
  "brands": [ ... ]
}
```
The client is skipped at build time and **does not count as a failure**, so the run stays green. The published `<slug>/index.html` is left untouched and keeps serving its last good data.

Use this when a brand disappears from the tracking platform but the report should stay online. Without it, the client fails on every run and the red build stops meaning anything.

---

## Add a brand to an existing report (multi-brand)

Add another object to the `brands` array in the config; the report gets a brand switch:
```json
{
  "brands": [
    { "id": "8fd9c9fe-...", "name": "El Corte Inglés (Casa)", "key": "elcorteingles_casa", "domain": "elcorteingles.pt" },
    { "id": "b2172ee8-...", "name": "El Corte Inglés", "key": "elcorteingles", "domain": "elcorteingles.pt" }
  ]
}
```

---

## Tracking accounts & API keys

Three tracking accounts are in use. The builder reads each client's key from the environment
variable named by its config (`api_key_env`, default `AIV_API_KEY`); `refresh.yml` and `labs.yml`
fill those variables from the repository secrets:
**https://github.com/GregUniK/ai-visibility/settings/secrets/actions**

| Variable | Account | Used by |
|---|---|---|
| `AIV_API_KEY` | analytics@unik-seo.com (main) | every client without `api_key_env` (coinsbee* and visitmadeira* paused) |
| `AIV_API_KEY_ECI` | Analytics2 | elcorteingles-casa, elcorteingles-sport |
| `AIV_API_KEY_LM` | Analytics1 — **account deleted 2026-07** | leroymerlin* |

\* paused — see the status table at the top.

Triage when a client fails (the run log names it, with the API's error):
- **`HTTP 403`** → the key or its account is dead. Account-side fix.
- **`HTTP 404` on the brand** → deleted from the tracking platform, or the config points at the
  wrong account. Check the brand id in the tracking dashboard (it is in the brand's URL), then fix
  `api_key_env` or pause the client.
- **Most prompt details failing** → the builder stops that client on purpose so a half-empty page
  doesn't replace the last good one; the others still build.

---

## Repo structure

```
configs/          ← one JSON per client (no API keys stored here)
<slug>/           ← built HTML reports committed here, served via GitHub Pages
tasks/index.html  ← hand-maintained index of the reports
labs/             ← the builder (labs/tools/), its tests, and the labs preview
.github/
  workflows/
    refresh.yml   ← the live reports, Mon + Thu + manual
    labs.yml      ← the labs preview, on every builder change + manual
```
