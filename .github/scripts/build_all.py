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
import json, os, shutil, subprocess, sys, pathlib

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

# ── Patch upstream build_fast.py to support skip_nlp ──────────────────────────
build_fast_path = BUILD_DIR / "build_fast.py"
src = build_fast_path.read_text(encoding="utf-8")

NLP_OLD = '    llm_cfg = {\n        "provider": provider,\n        "api_key": llm_api_key,\n        "model": llm_model,\n        "base_url": llm_base_url,\n    }'
NLP_NEW = '    llm_cfg = None if cfg.get("skip_nlp") else {\n        "provider": provider,\n        "api_key": llm_api_key,\n        "model": llm_model,\n        "base_url": llm_base_url,\n    }'

ACT_OLD = '        ACTIONS[brand_key] = generate_actions(cfg, brand_name, brand_domain, brand_data)'
ACT_NEW = '        ACTIONS[brand_key] = [] if cfg.get("skip_nlp") else generate_actions(cfg, brand_name, brand_domain, brand_data)'

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

if patched:
    build_fast_path.write_text(src, encoding="utf-8")

# ── Auto-discover clients from configs/ ───────────────────────────────────────
CLIENTS = sorted(p.stem for p in CONFIGS.glob("*.json"))
print(f"\nDiscovered {len(CLIENTS)} clients: {', '.join(CLIENTS)}")

succeeded = []
failed    = []

for slug in CLIENTS:
    print(f"\n{'='*40}\n{slug}\n{'='*40}")

    cfg_path = CONFIGS / f"{slug}.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

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

    # Copy actions stub — prevents action generation entirely
    stub = STUBS / f"{slug}.json"
    if not stub.exists():
        print(f"  WARNING — no stub found at stubs/{slug}.json, creating empty one")
        stub.write_text("[]", encoding="utf-8")
    shutil.copy(stub, BUILD_DIR / f"actions_{slug}.json")

    result = subprocess.run(
        [sys.executable, str(BUILD_DIR / "build_fast.py"), "--config", str(tmp_cfg)],
        cwd=str(BUILD_DIR),
        capture_output=False
    )

    if result.returncode != 0:
        print(f"  FAILED: {slug}")
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
print(f"\n{'='*40}")
print(f"Built:  {len(succeeded)}/{len(CLIENTS)} — {', '.join(succeeded) or 'none'}")
if failed:
    print(f"Failed: {', '.join(failed)}")

# Exit 0 if at least some clients succeeded so the commit step always runs.
# Exit 1 only if EVERYTHING failed (nothing to commit).
if succeeded:
    sys.exit(0)
else:
    sys.exit(1)
