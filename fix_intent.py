"""Inject `intent` into D_ORIG.prompts[brand][] from RAW_HISTORY.prompts[].

Fix for the bug where the default "all time" view of the Prompts tab shows
"-" for the Intent column. The renderer reads from D.prompts[bk] which in
that view equals D_ORIG.prompts[bk] directly — and D_ORIG never carried the
intent field, while RAW_HISTORY did.

Reads each <slug>/index.html, parses D_ORIG and RAW_HISTORY, maps
{promptId: intent} from RAW_HISTORY, mirrors it into each D_ORIG prompt row,
and writes the HTML back with the D_ORIG block replaced.

Uses a callable as the regex replacement to avoid re.sub's backslash
interpretation of JSON \n escapes.

Run:
    python fix_intent.py                 # patch all reports
    python fix_intent.py credibom xtb    # patch specific slugs
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
SLUGS = [
    "coinsbee", "credibom", "era", "reduniq", "unikseo", "visitmadeira",
    "wizink-es", "wizink-pt", "xtb", "elcorteingles-casa", "elcorteingles-sport",
    # leroymerlin handled separately — it lacks the Intent column infra entirely
]


def extract_const(html, name):
    pat = re.compile(rf"^const {re.escape(name)}=(.*?);\s*$", re.MULTILINE)
    m = pat.search(html)
    if not m:
        raise RuntimeError(f"const {name} block not found")
    return m.group(1), m.span()


def replace_const(html, name, new_json):
    """String-splice replacement — regex sub on huge JSON values OOMs."""
    marker = f"\nconst {name}="
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(f"const {name} not found on inject")
    # Find end of statement: end of line + ; (handle the const on one line)
    line_start = start + 1  # past leading \n
    end_marker = ";"
    # Walk to the matching ; that ends the line containing the const
    pos = line_start
    while True:
        nl = html.find("\n", pos)
        if nl < 0:
            raise RuntimeError(f"const {name} unterminated")
        # check the char before nl is ;
        # (lines are: const NAME=...;\n)
        if html[nl - 1] == ";":
            line_end = nl
            break
        pos = nl + 1
    new_html = html[:line_start] + f"const {name}={new_json};" + html[line_end:]
    return new_html


def fix_one(slug):
    fp = HERE / slug / "index.html"
    if not fp.exists():
        print(f"  {slug}: file missing"); return
    html = fp.read_text(encoding="utf-8")

    d_orig_raw, _ = extract_const(html, "D_ORIG")
    rh_raw, _ = extract_const(html, "RAW_HISTORY")
    d_orig = json.loads(d_orig_raw)
    rh = json.loads(rh_raw)

    # Build {promptId: intent} from RAW_HISTORY
    pid_intent = {}
    for slug_key, brand_data in rh.items():
        for rp in brand_data.get("prompts", []):
            if rp.get("intent"):
                pid_intent[rp["id"]] = rp["intent"]

    # Inject into D_ORIG.prompts
    prompts_dict = d_orig.get("prompts", {})
    total_rows = 0
    enriched = 0
    for brand_key, rows in prompts_dict.items():
        for row in rows:
            total_rows += 1
            rid = row.get("id")
            if rid and rid in pid_intent and not row.get("intent"):
                row["intent"] = pid_intent[rid]
                enriched += 1

    new_d_orig = json.dumps(d_orig, ensure_ascii=False)
    new_html = replace_const(html, "D_ORIG", new_d_orig)
    fp.write_text(new_html, encoding="utf-8", newline="\n")
    print(f"  {slug}: enriched {enriched}/{total_rows} D_ORIG rows ({fp.stat().st_size:,} bytes)")


def main(argv):
    targets = argv if argv else SLUGS
    for slug in targets:
        try:
            fix_one(slug)
        except Exception as e:
            print(f"  {slug}: ERROR {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
