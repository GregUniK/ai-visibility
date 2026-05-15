"""
build_all.py — builds all ai-visibility client reports and copies them into
the repo folder structure ready for git commit.

Reads brand configs from configs/<slug>.json (no API key stored there).
Each config may specify an "api_key_env" field naming which GitHub secret
to use; defaults to AIPEEKABOO_API_KEY.
Patches build_fast.py from upstream to support skip_nlp (no LLM calls).

GitHub secrets required:
  AIPEEKABOO_API_KEY      — main account (pk_3c86bc8c...) — most clients
  AIPEEKABOO_API_KEY_ECI  — El Corte Inglés account (pk_7ca3f413...)
  AIPEEKABOO_API_KEY_LM   — Leroy Merlin account (pk_2470d153...)
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

# Fail fast if main key is missing; warn only for optional ones
if not API_KEYS["AIPEEKABOO_API_KEY"]:
    sys.exit("ERROR: AIPEEKABOO_API_KEY env var not set")

# ── Patch upstream build_fast.py to support skip_nlp ──────────────────────────
# The upstream build_fast.py has no skip_nlp support. We patch it once so that
# setting skip_nlp:true in a config bypasses both NLP extraction and action
# generation — zero LLM calls, zero tokens.
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
    print("Patched build_fast.py: skip_nlp support added (NLP pass)")
else:
    print("WARNING: could not apply skip_nlp NLP patch (upstream may have changed)")

if ACT_OLD in src:
    src = src.replace(ACT_OLD, ACT_NEW)
    patched = True
    print("Patched build_fast.py: skip_nlp support added (action generation)")
else:
    print("WARNING: could not apply skip_nlp actions patch (upstream may have changed)")

if patched:
    build_fast_path.write_text(src, encoding="utf-8")

# ── Build each client ──────────────────────────────────────────────────────────
# Each config file may include "api_key_env": "<SECRET_NAME>" to select which
# GitHub secret holds its PeekaBoo API key. Defaults to AIPEEKABOO_API_KEY.
CLIENTS = [
    "coinsbee", "credibom", "elcorteingles", "era",
    "leroymerlin", "reduniq", "unikseo", "visitmadeira", "xtb"
]

failed = []

for slug in CLIENTS:
    print(f"\n{'='*40}\n{slug}\n{'='*40}")

    # Load brand config
    cfg_path = CONFIGS / f"{slug}.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    # Resolve the correct API key for this client
    key_env = cfg.get("api_key_env", "AIPEEKABOO_API_KEY")
    api_key = API_KEYS.get(key_env, "")
    if not api_key:
        print(f"  SKIPPED: {slug} — secret {key_env!r} not set in environment")
        failed.append(slug)
        continue

    cfg["aipeekaboo_api_key"] = api_key
    cfg["skip_nlp"] = True
    cfg["llm_provider"] = "claude-cli"   # skips llm_api_key validation check

    # Write temp config
    tmp_cfg = TMP / f"config_{slug}.json"
    tmp_cfg.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Copy actions stub → action generation is skipped (file already exists)
    shutil.copy(STUBS / f"{slug}.json", BUILD_DIR / f"actions_{slug}.json")

    # Run build
    result = subprocess.run(
        [sys.executable, str(BUILD_DIR / "build_fast.py"), "--config", str(tmp_cfg)],
        cwd=str(BUILD_DIR),
        capture_output=False
    )

    if result.returncode != 0:
        print(f"  FAILED: {slug}")
        failed.append(slug)
        continue

    # Copy output HTML into repo subfolder
    out_file = cfg.get("output_file", "report.html")
    src_html = BUILD_DIR / out_file
    dst_dir  = ROOT / slug
    dst_dir.mkdir(exist_ok=True)
    shutil.copy(src_html, dst_dir / "index.html")
    print(f"  -> {slug}/index.html")

if failed:
    print(f"\nFailed: {failed}")
    sys.exit(1)

print("\nAll clients built successfully.")
