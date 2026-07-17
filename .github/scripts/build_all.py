"""
build_all.py — builds all ai-visibility client reports and copies them into
the repo folder structure ready for git commit.

Clients are auto-discovered from configs/<slug>.json — no hardcoded list.
Each config may specify "api_key_env" naming which GitHub secret to use;
defaults to AIPEEKABOO_API_KEY.
Patches build_fast.py from upstream to support skip_nlp (no LLM calls).

GitHub secrets:
  AIPEEKABOO_API_KEY      — main account (analytics@unik-seo.com)
  AIPEEKABOO_API_KEY_ECI  — Analytics2 account (El Corte Inglés)
  AIPEEKABOO_API_KEY_LM   — Analytics1 account (Leroy Merlin)
"""
import json, os, shutil, subprocess, sys, pathlib, urllib.request, urllib.error

ROOT      = pathlib.Path(__file__).parent.parent.parent   # repo root
BUILD_DIR = ROOT / "build-tools"
CONFIGS   = ROOT / "configs"
STUBS     = ROOT / "stubs"
TMP       = pathlib.Path("/tmp/ai-visibility-build")
TMP.mkdir(exist_ok=True)

# Load all available API keys from environment
API_KEYS = {
    "AIPEEKABOO_API_KEY":     os.environ.get("AIPEEKABOO_API_KEY", ""),
    "AIPEEKABOO_API_KEY_ECI": os.environ.get("AIPEEKABOO_API_KEY_ECI", ""),
    "AIPEEKABOO_API_KEY_LM":  os.environ.get("AIPEEKABOO_API_KEY_LM", ""),
}

if not API_KEYS["AIPEEKABOO_API_KEY"]:
    sys.exit("ERROR: AIPEEKABOO_API_KEY env var not set")


def diagnose(cfg, api_key):
    """Ask the API directly why a client failed, using the key we resolved.

    build_fast.py raises on a bare raise_for_status(), so the response body —
    which carries PeekaBoo's real error code — never reaches the log; all the
    build shows is "404 Client Error". Re-run the first prompts call here with
    the resolved key and print the actual body. Only runs after a failure, so
    it costs nothing on the happy path. A 200 here while the build 404s means
    the build used a different key than this one (see the env note below).
    """
    for brand in cfg.get("brands", []):
        bid, name = brand.get("id"), brand.get("name", "?")
        url = f"https://www.aipeekaboo.com/api/v1/brands/{bid}/prompts?limit=200&offset=0"
        try:
            req = urllib.request.Request(url, headers={"X-API-Key": api_key})
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"  probe {name} [{bid}]: HTTP {resp.status} OK with the "
                      f"resolved key — build must have used a different key")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace").strip()[:300]
            print(f"  probe {name} [{bid}]: HTTP {e.code} — {body}")
        except Exception as e:
            print(f"  probe {name} [{bid}]: {type(e).__name__} — {e}")

# Validate each API key by listing accessible brands (output is NOT masked by GitHub)
print("\n── Key → Brand validation ──────────────────────────────────────────")
for key_name, key_value in API_KEYS.items():
    if not key_value:
        print(f"  {key_name}: [not set]")
        continue
    try:
        req = urllib.request.Request(
            "https://www.aipeekaboo.com/api/v1/brands",
            headers={"X-API-Key": key_value}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            brands = data if isinstance(data, list) else data.get("brands", data.get("data", []))
            print(f"  {key_name}: {len(brands)} brand(s)")
            # Print ids, not just names: a client that 404s while its name shows
            # up here means the id in its config doesn't match the real brand.
            for b in brands:
                print(f"      {b.get('id', '?')}  {b.get('name', '?')}")
    except urllib.error.HTTPError as e:
        print(f"  {key_name}: HTTP {e.code} — {e.reason}")
    except Exception as e:
        print(f"  {key_name}: ERROR — {e}")
print()

# ── Patch upstream build_fast.py to support skip_nlp ──────────────────────────
build_fast_path = BUILD_DIR / "build_fast.py"
src = build_fast_path.read_text(encoding="utf-8")

NLP_OLD = '    llm_cfg = {\n        "provider": provider,\n        "api_key": llm_api_key,\n        "model": llm_model,\n        "base_url": llm_base_url,\n    }'
NLP_NEW = '    llm_cfg = None if cfg.get("skip_nlp") else {\n        "provider": provider,\n        "api_key": llm_api_key,\n        "model": llm_model,\n        "base_url": llm_base_url,\n    }'

ACT_OLD = '        ACTIONS[brand_key] = generate_actions(cfg, brand_name, brand_domain, brand_data)'
ACT_NEW = '        ACTIONS[brand_key] = [] if cfg.get("skip_nlp") else generate_actions(cfg, brand_name, brand_domain, brand_data)'

# Patch A: offset-based pagination for /brands/:id/prompts.
# Upstream uses `page` param which the API silently ignores, causing infinite loops
# for any brand with >200 prompts (e.g. El Corte Inglés casa & sport, 250 each).
PAGE_OLD = (
    'def fetch_all_prompts(api_key, brand_id):\n'
    '    """Fetch all prompts for a brand with pagination."""\n'
    '    prompts = []\n'
    '    page = 1\n'
    '    while True:\n'
    '        data = api_get(api_key, f"/brands/{brand_id}/prompts",\n'
    '                       params={"limit": 200, "page": page})\n'
    '        batch = data.get("prompts") or data.get("data") or []\n'
    '        prompts.extend(batch)\n'
    '        pagination = data.get("pagination", {})\n'
    '        if not pagination.get("hasMore", False):\n'
    '            break\n'
    '        page += 1\n'
    '    return prompts'
)
PAGE_NEW = (
    'def fetch_all_prompts(api_key, brand_id):\n'
    '    """Fetch all prompts for a brand with pagination (offset-based)."""\n'
    '    prompts = []\n'
    '    offset = 0\n'
    '    limit = 200\n'
    '    while True:\n'
    '        data = api_get(api_key, f"/brands/{brand_id}/prompts",\n'
    '                       params={"limit": limit, "offset": offset})\n'
    '        batch = data.get("prompts") or data.get("data") or []\n'
    '        if not batch:\n'
    '            break\n'
    '        prompts.extend(batch)\n'
    '        pagination = data.get("pagination", {})\n'
    '        print(f"    page offset={offset} got={len(batch)} total={pagination.get(\'total\',\'?\')} hasMore={pagination.get(\'hasMore\', False)}", flush=True)\n'
    '        if not pagination.get("hasMore", False):\n'
    '            break\n'
    '        offset += limit\n'
    '        if offset >= 10000:\n'
    '            print(f"    WARNING: pagination safety break at offset={offset}", flush=True)\n'
    '            break\n'
    '    return prompts'
)

# Patch B: bump rate limit from 3.2s (20 req/min, old Grow plan) to 1.6s (40 req/min, upgraded plan).
RATE_OLD = '_MIN_FETCH_INTERVAL = 3.2  # seconds between calls to stay under 20 req/min'
RATE_NEW = '_MIN_FETCH_INTERVAL = 1.6  # seconds between calls to stay under 40 req/min (upgraded plan)'

# Patch C: load config as UTF-8 explicitly.
# On Windows runners (or any locale where the default isn't UTF-8), `open(path)` falls
# back to cp1252 and mangles non-ASCII brand names (e.g. "Inglés" -> "InglÃ©s").
# Linux CI runners default to UTF-8 so this is a safety patch.
ENC_OLD = '    with open(path) as f:\n        cfg = json.load(f)'
ENC_NEW = '    with open(path, encoding="utf-8") as f:\n        cfg = json.load(f)'

patched = False
if NLP_OLD in src:
    src = src.replace(NLP_OLD, NLP_NEW)
    patched = True
    print("Patched build_fast.py: skip_nlp (NLP pass)")
else:
    print("WARNING: skip_nlp NLP patch not applied — upstream may have changed")

if ACT_OLD in src:
    src = src.replace(ACT_OLD, ACT_NEW)
    patched = True
    print("Patched build_fast.py: skip_nlp (action generation)")
else:
    print("WARNING: skip_nlp actions patch not applied — upstream may have changed")

if PAGE_OLD in src:
    src = src.replace(PAGE_OLD, PAGE_NEW)
    patched = True
    print("Patched build_fast.py: offset-based pagination (fixes infinite loop for >200 prompts)")
else:
    print("WARNING: pagination patch not applied — upstream may have changed")

if RATE_OLD in src:
    src = src.replace(RATE_OLD, RATE_NEW)
    patched = True
    print("Patched build_fast.py: rate limit 3.2s -> 1.6s (upgraded API plan)")
else:
    print("WARNING: rate limit patch not applied — upstream may have changed")

if ENC_OLD in src:
    src = src.replace(ENC_OLD, ENC_NEW)
    patched = True
    print("Patched build_fast.py: UTF-8 config encoding (fixes 'Inglés' mangling)")
else:
    print("WARNING: utf-8 config encoding patch not applied — upstream may have changed")

if patched:
    build_fast_path.write_text(src, encoding="utf-8")

# ── Auto-discover clients from configs/ ───────────────────────────────────────
CLIENTS = sorted(p.stem for p in CONFIGS.glob("*.json"))
print(f"\nDiscovered {len(CLIENTS)} clients: {', '.join(CLIENTS)}")

succeeded = []
failed    = []
paused    = []

for slug in CLIENTS:
    print(f"\n{'='*40}\n{slug}\n{'='*40}")

    cfg_path = CONFIGS / f"{slug}.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    # Paused clients are intentionally not built (e.g. brand removed from
    # PeekaBoo) but their existing report stays published. Not a failure —
    # otherwise every run would go red forever and the signal would be lost.
    if cfg.get("paused"):
        print(f"  PAUSED — {cfg.get('paused_reason', 'no reason given')}")
        paused.append(slug)
        continue

    # Resolve API key for this client
    key_env = cfg.get("api_key_env", "AIPEEKABOO_API_KEY")
    api_key = API_KEYS.get(key_env, "")
    if not api_key:
        print(f"  SKIPPED — secret '{key_env}' not set in environment")
        failed.append(slug)
        continue

    cfg["aipeekaboo_api_key"] = api_key
    cfg["skip_nlp"] = True
    cfg["llm_provider"] = "claude-cli"   # bypasses llm_api_key validation

    tmp_cfg = TMP / f"config_{slug}.json"
    tmp_cfg.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Copy actions stub — prevents action generation entirely.
    # build_fast.py looks up actions by brand["key"] which may differ from the
    # slug (e.g. slug="elcorteingles-casa" but key="elcorteingles_casa"). Copy
    # under both names to cover every config shape.
    stub = STUBS / f"{slug}.json"
    if not stub.exists():
        print(f"  WARNING — no stub found at stubs/{slug}.json, creating empty one")
        stub.write_text("[]", encoding="utf-8")
    shutil.copy(stub, BUILD_DIR / f"actions_{slug}.json")
    for brand in cfg.get("brands", []):
        bk = brand.get("key")
        if bk and bk != slug:
            shutil.copy(stub, BUILD_DIR / f"actions_{bk}.json")

    # build_fast.py's load_config() overrides cfg["aipeekaboo_api_key"] with the
    # AIPEEKABOO_API_KEY env var whenever it is set — and in CI it always is (the
    # main key). That silently makes every client use the main key regardless of
    # api_key_env, so non-main brands (El Corte Inglés on Analytics2) 404 with
    # "Brand not found". Point that env var at THIS client's resolved key so the
    # upstream override picks the right account instead of clobbering it.
    sub_env = dict(os.environ)
    sub_env["AIPEEKABOO_API_KEY"] = api_key

    result = subprocess.run(
        [sys.executable, str(BUILD_DIR / "build_fast.py"), "--config", str(tmp_cfg)],
        cwd=str(BUILD_DIR),
        capture_output=False,
        env=sub_env
    )

    if result.returncode != 0:
        print(f"  FAILED: {slug}")
        diagnose(cfg, api_key)
        failed.append(slug)
        continue

    out_file = cfg.get("output_file", "report.html")
    src_html = BUILD_DIR / out_file
    dst_dir  = ROOT / slug
    dst_dir.mkdir(exist_ok=True)

    # Post-process HTML: inject noindex + remove Actions tab
    html = src_html.read_text(encoding="utf-8")

    NOINDEX = '<meta name="robots" content="noindex,nofollow">'
    if NOINDEX not in html:
        html = html.replace("<head>", f"<head>\n  {NOINDEX}", 1)

    html = html.replace('<button class="stab" onclick="switchTab(\'actions\',this)">Actions</button>', '')
    tag = '<div id="panel-actions"'
    start = html.find(tag)
    if start != -1:
        depth, i = 0, start
        while i < len(html):
            if html[i:i+4] == '<div': depth += 1
            elif html[i:i+6] == '</div>':
                depth -= 1
                if depth == 0:
                    html = html[:start] + html[i+6:]
                    break
            i += 1

    (dst_dir / "index.html").write_text(html, encoding="utf-8")

    print(f"  -> {slug}/index.html")
    succeeded.append(slug)

# ── Summary ───────────────────────────────────────────────────────────────────
expected = len(CLIENTS) - len(paused)
print(f"\n{'='*40}")
print(f"Built:  {len(succeeded)}/{expected} — {', '.join(succeeded) or 'none'}")
if paused:
    print(f"Paused: {', '.join(paused)} (not built by design)")
if failed:
    print(f"Failed: {', '.join(failed)}")

# Exit non-zero if ANY non-paused client failed, so the run goes red and the
# "Notify on failure" step opens an issue. The commit step runs regardless
# (if: !cancelled() in refresh.yml), so reports that did build still ship.
if failed:
    sys.exit(f"\nERROR: {len(failed)} client(s) failed to build: {', '.join(failed)}")
sys.exit(0)
