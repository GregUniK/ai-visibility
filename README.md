# AI Visibility Reports — GregUniK

Auto-refreshed PeekaBoo AI visibility reports published to GitHub Pages.

**Live reports:** `https://gregunik.github.io/ai-visibility/<client>/`

| Client | URL |
|---|---|
| CoinsBee | https://gregunik.github.io/ai-visibility/coinsbee/ |
| Credibom | https://gregunik.github.io/ai-visibility/credibom/ |
| El Corte Inglés | https://gregunik.github.io/ai-visibility/elcorteingles/ |
| ERA Imobiliária | https://gregunik.github.io/ai-visibility/era/ |
| Leroy Merlin | https://gregunik.github.io/ai-visibility/leroymerlin/ |
| REDUNIQ | https://gregunik.github.io/ai-visibility/reduniq/ |
| UniK SEO | https://gregunik.github.io/ai-visibility/unikseo/ |
| Visitmadeira | https://gregunik.github.io/ai-visibility/visitmadeira/ |
| XTB | https://gregunik.github.io/ai-visibility/xtb/ |

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
| `AIPEEKABOO_API_KEY` | analytics@unik-seo.com (main) | coinsbee, credibom, era, reduniq, unikseo, visitmadeira, xtb |
| `AIPEEKABOO_API_KEY_ECI` | Analytics2 | elcorteingles |
| `AIPEEKABOO_API_KEY_LM` | Analytics1 | leroymerlin |

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
