"""
build_all.py — builds all ai-visibility client reports and copies them into
the repo folder structure ready for git commit.

Reads brand configs from configs/<slug>.json (no API key stored there).
Injects AIPEEKABOO_API_KEY from environment.
Skips NLP and action generation (skip_nlp: true, actions stubs from stubs/).
"""
import json, os, shutil, subprocess, sys, pathlib

ROOT      = pathlib.Path(__file__).parent.parent.parent   # repo root
BUILD_DIR = ROOT / "build-tools"
CONFIGS   = ROOT / "configs"
STUBS     = ROOT / "stubs"
TMP       = pathlib.Path("/tmp/ai-visibility-build")
TMP.mkdir(exist_ok=True)

API_KEY = os.environ.get("AIPEEKABOO_API_KEY", "")
if not API_KEY:
    sys.exit("ERROR: AIPEEKABOO_API_KEY env var not set")

CLIENTS = [
    "coinsbee", "credibom", "elcorteingles", "era",
    "leroymerlin", "reduniq", "unikseo", "visitmadeira", "xtb"
]

failed = []

for slug in CLIENTS:
    print(f"\n{'='*40}\n{slug}\n{'='*40}")

    # Load brand config and inject API key
    cfg_path = CONFIGS / f"{slug}.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["aipeekaboo_api_key"] = API_KEY
    cfg["skip_nlp"] = True
    cfg["llm_provider"] = "claude-cli"   # keeps llm_api_key check quiet

    # Write temp config into build dir
    tmp_cfg = TMP / f"config_{slug}.json"
    tmp_cfg.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Copy actions stub so action generation is skipped
    stub_src = STUBS / f"{slug}.json"
    stub_dst = BUILD_DIR / f"actions_{slug}.json"
    shutil.copy(stub_src, stub_dst)

    # Run build
    result = subprocess.run(
        [sys.executable, str(BUILD_DIR / "build_fast.py"),
         "--config", str(tmp_cfg)],
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
    print(f"  -> copied to {slug}/index.html")

if failed:
    print(f"\nFailed clients: {failed}")
    sys.exit(1)

print("\nAll clients built successfully.")
