"""Tests for build_labs.py's data shaping. No network: a fake API serves dicts."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import build_labs as bl  # noqa: E402

BID = "brand-1"


class FakeAPI:
    def __init__(self, routes):
        self.routes = routes
        self.calls = 0
        self.seen = []

    def get(self, path, params=None):
        self.calls += 1
        self.seen.append((path, dict(params or {})))
        key = (path, (params or {}).get("offset"))
        if key in self.routes:
            return self.routes[key]
        if path in self.routes:
            return self.routes[path]
        raise bl.ApiError(f"404 {path}")


def entry(date, model, hit, run, comps=(), score=0, rank=None):
    return {"runId": run, "date": date, "aiModel": model, "mentioned": hit, "score": score, "rank": rank,
            "sentiment": "positive" if hit else None, "fullResponse": "Acme is good" if hit else "nothing",
            "sources": [{"url": "https://x.pt/a", "title": "A"}],
            "brandMentions": [{"entityName": n, "type": t} for n, t in comps]}


def brand_routes():
    return {
        f"/brands/{BID}/prompts": {"success": True, "data": [
            {"promptId": "p1", "promptText": "best loans", "category": "Loans", "searchIntent": "COMMERCIAL",
             "status": "active"},
            {"promptId": "p2", "promptText": "old prompt", "category": "Loans", "searchIntent": "INFORMATIONAL",
             "status": "archived"},
        ]},
        f"/brands/{BID}/prompts/p1": {"success": True, "data": {
            "summary": {"truncated": True, "historyLimit": 100},
            # newest first, as the API returns it
            "history": [
                entry("2026-10-03", "gpt-4o-mini", True, "r3", [("Rival", "competitor")], 100, 1),
                entry("2026-09-28", "gpt-4o-mini", False, "r2", [("Bank of X", "untracked")]),
                entry("2026-07-09", "gpt-4o-mini", False, "r1"),
            ]}},
    }


def test_archived_prompts_are_left_out_and_listed():
    data = bl.process_brand(FakeAPI(brand_routes()), {"id": BID, "name": "Acme"})
    assert [p["id"] for p in data["prompts"]] == ["p1"]
    assert data["inactive"] == [{"id": "p2", "text": "old prompt", "status": "archived"}]


def test_latest_result_per_model_is_the_newest_run():
    data = bl.process_brand(FakeAPI(brand_routes()), {"id": BID, "name": "Acme"})
    latest = data["prompts"][0]["models"]["gpt-4o-mini"]
    assert latest["mentioned"] is True and latest["rank"] == 1
    assert data["prompts"][0]["mentions"] == 1 and data["prompts"][0]["totalRuns"] == 3


def test_run_ids_types_and_history_cap_are_kept():
    data = bl.process_brand(FakeAPI(brand_routes()), {"id": BID, "name": "Acme"})
    entries = data["raw_history"]["prompts"][0]["entries"]
    assert [e["rid"] for e in entries] == ["r3", "r2", "r1"]
    assert data["entity_types"] == {"Rival": ["competitor"], "Bank of X": ["untracked"]}
    assert data["capped"] == [{"id": "p1", "text": "best loans"}]


def test_tracked_competitors_merge_api_list_and_mention_types():
    official = {"competitors": [{"name": "Rival", "url": "https://www.rival.pt/"},
                                {"name": "Quiet Co", "url": "https://quiet.pt"}]}
    types = {"Rival": ["competitor"], "Bank of X": ["untracked"], "Other": ["competitor"]}
    assert bl.tracked_competitors(official, types) == ["Other", "Quiet Co", "Rival"]
    assert bl.tracked_domains(official, ["Rival", "Quiet Co", "Bank of X"]) == {"Rival": "rival.pt",
                                                                                 "Quiet Co": "quiet.pt"}


@pytest.mark.parametrize("a,b,same", [
    ("Cofidis Portugal", "Cofidis", True),
    ("Younited", "Younited Credit", True),
    ("Oney Bank", "Oney", True),
    ("Banco Credibom", "Credibom", True),
    ("novobanco", "Novobanco", True),
    ("Santander", "Santander Consumer Finance", False),
    ("Caixa", "Caixa Geral de Depósitos", False),
    ("DECO", "DECO PROteste", False),
    ("Banco", "Banco CTT", False),
    ("Otterly AI", "otterly.ai", True),
    ("SEO", "SEO Labs", False),  # dropping "Labs" leaves a stub, not a company
    ("SEO.com", "SEO Labs", False),
    ("SEO", "seo", True),
    ("Hôma", "Homa", True),  # accents don't count
    ("Cételem", "Cetelem Portugal", True),
])
def test_same_name_matches_spellings_not_related_companies(a, b, same):
    assert bl.same_name(a, b) is same


@pytest.mark.parametrize("domain,stem", [
    ("era.pt", "era"), ("www.unik-seo.com", "unikseo"), ("https://foo.com.pt/x", "foo"),
    ("info.vortal.biz", "vortal"), ("app.n26.com", "n26"), ("empresas.ing.es", "ing"),
    ("base.gov.pt", "base"), ("", ""),
])
def test_domain_stem(domain, stem):
    assert bl.domain_stem(domain) == stem


def test_brand_self_names_drop_the_market_label_and_spell_the_domain():
    assert bl.brand_self_names("El Corte Inglés (Casa)", "elcorteingles.pt") == [
        "El Corte Inglés (Casa)", "El Corte Inglés"]
    assert bl.brand_self_names("ERA Imobiliaria", "era.pt") == ["ERA Imobiliaria", "ERA"]
    assert bl.brand_self_names("UniK SEO", "unik-seo.com") == ["UniK SEO"]


@pytest.mark.parametrize("name,brand,domain,self_", [
    ("ERA Portugal", "ERA Imobiliaria", "era.pt", True),
    ("Adelante Shoes", "Adelante", "adelanteshoes.com", True),
    ("El Corte Inglés Portugal", "El Corte Inglés (Sport)", "elcorteingles.pt", True),
    ("WiZink Bank", "WiZink (España)", "wizink.es", True),
    ("Century 21 Portugal", "ERA Imobiliaria", "era.pt", False),
    ("SEO", "UniK SEO", "unik-seo.com", False),
])
def test_is_self_name(name, brand, domain, self_):
    assert bl.is_self_name(name, brand, domain) is self_


def test_alias_knows_the_brand_by_its_domain_and_keeps_stubs_apart():
    alias, aliases = bl.make_alias("ERA Imobiliaria", ["SEO Labs", "Century 21 Portugal"], {}, "era.pt")
    assert alias("ERA Portugal") is None
    assert alias("SEO") == "SEO" and alias("SEO.com") == "SEO.com"
    assert alias("Century 21") == "Century 21 Portugal"
    assert {k: sorted(v) for k, v in aliases.items()} == {
        "ERA Imobiliaria": ["ERA", "ERA Portugal"], "Century 21 Portugal": ["Century 21"]}


def test_a_word_of_the_brand_name_alone_is_the_category_not_a_competitor():
    alias, aliases = bl.make_alias("UniK SEO", ["SEO Labs"], {}, "unik-seo.com")
    assert alias("SEO") is None and alias("seo") is None
    assert alias("SEO.com") == "SEO.com" and alias("SEO Labs") == "SEO Labs"
    assert dict(aliases) == {}
    alias, _ = bl.make_alias("Credibom", [], {}, "credibom.pt")  # a one-word name has no such words
    assert alias("Cofidis") == "Cofidis"


def test_brand_context_finds_the_name_without_its_label():
    text = "x" * 500 + " A El Corte Inglés tem ótimas lojas."
    ctx = bl._brand_context(text, ["El Corte Inglés (Casa)", "El Corte Inglés"], 100)
    assert "El Corte Inglés tem" in ctx and ctx.startswith("…")
    # a short name must be written as the brand writes it: "era" is a word
    assert bl._brand_context("Esta era a melhor. " + "y" * 300, ["ERA"], 40) == ("Esta era a melhor. " + "y" * 300)[:40]


def test_tracked_lists_and_domains_follow_same_name():
    official = {"competitors": [{"name": "Younited Credit", "url": "https://younited-credit.pt"},
                                {"name": "Banco CTT", "url": "https://bancoctt.pt"}]}
    types = {"Younited": ["untracked"], "Banco": ["untracked"]}
    assert bl.tracked_competitors(official, types) == ["Banco CTT", "Younited", "Younited Credit"]
    assert bl.tracked_domains(official, ["Younited", "Banco"]) == {"Younited": "younited-credit.pt"}


def test_alias_prefers_competitor_id_then_names():
    alias, aliases = bl.make_alias("Credibom", ["Younited Credit", "Cofidis", "Oney"], {"id-1": "Cofidis"})
    assert alias("Something Odd", "id-1") == "Cofidis"
    assert alias("Banco Credibom") is None and alias("Credibom") is None
    assert alias("Younited") == "Younited Credit"
    assert alias("Cofidis Portugal") == "Cofidis"
    assert alias("Banco CTT") == "Banco CTT"
    assert {k: sorted(v) for k, v in aliases.items()} == {
        "Cofidis": ["Cofidis Portugal", "Something Odd"], "Credibom": ["Banco Credibom"],
        "Younited Credit": ["Younited"]}


def test_process_brand_applies_aliases_and_counts_a_name_once_per_answer():
    routes = brand_routes()
    routes[f"/brands/{BID}/prompts/p1"]["data"]["history"][1]["brandMentions"] = [
        {"entityName": "Banco Credibom", "type": "untracked"}, {"entityName": "Rival Portugal", "type": "untracked"},
        {"entityName": "Rival", "type": "competitor", "competitorId": "c-rival"},
        {"entityName": "Younited", "type": "untracked"}]
    data = bl.process_brand(FakeAPI(routes), {"id": BID, "name": "Credibom"}, ["Rival", "Younited Credit"],
                            {"c-rival": "Rival"})
    by_name = {c["name"]: c["mentions"] for c in data["competitors"]}
    assert "Banco Credibom" not in by_name and "Younited" not in by_name
    assert by_name["Rival"] == 2  # "Rival Portugal" and "Rival" in one answer count once, plus the newest run
    assert data["raw_history"]["prompts"][0]["entries"][1]["comps"] == ["Rival", "Younited Credit"]
    assert data["aliases"] == {"Credibom": ["Banco Credibom"], "Rival": ["Rival Portugal"],
                               "Younited Credit": ["Younited"]}


def test_most_prompt_details_failing_stops_the_build():
    routes = brand_routes()
    del routes[f"/brands/{BID}/prompts/p1"]
    with pytest.raises(bl.ApiError):
        bl.process_brand(FakeAPI(routes), {"id": BID, "name": "Acme"})


def _prompt(pid, dates, models):
    return {"id": pid, "entries": [{"date": d, "model": m} for d in dates for m in models]}


def test_partial_runs_does_not_flag_a_model_after_it_was_dropped():
    prompts = [_prompt(f"p{i}", "abcd", "xy") for i in range(5)] + [_prompt(f"z{i}", "ab", "z") for i in range(5)]
    assert bl.partial_runs(prompts) == []


def test_partial_runs_skips_dates_cut_by_the_history_cap():
    # 2 prompts at the 100-run cap keep only dates b-d, so date "a" looks thin without the floor.
    prompts = [_prompt(f"p{i}", "abcd", "xy") for i in range(4)] + [_prompt(f"c{i}", "bcd", "xy") for i in range(2)]
    assert bl.partial_runs(prompts) != []  # without telling it which prompts are capped
    assert bl.partial_runs(prompts, capped_ids=[f"c{i}" for i in range(2)]) == []


def test_partial_runs_flags_missing_and_low_models_only():
    def p(entries):
        return {"entries": [{"date": d, "model": m} for d, m in entries]}
    prompts = []
    for i in range(10):
        e = [("2026-08-01", "aio"), ("2026-08-01", "gpt"), ("2026-08-06", "gpt"), ("2026-08-11", "gpt"),
             ("2026-08-11", "aio")]
        if i < 4:
            e.append(("2026-08-06", "aio"))  # aio answered only 4 of 10 on 08-06
        prompts.append(p(e))
    prompts.append(p([("2026-08-11", "new-model")]))  # starts late: never flagged before it began
    notes = bl.partial_runs(prompts)
    assert notes == [{"date": "2026-08-06", "model": "aio", "count": 4, "typical": 10}]


def test_partial_runs_checks_only_run_dates():
    # Adelante's shape: 10 days of 3 prompts a day, then 4 full runs of all 30 prompts, where
    # model y answered only 13 on the third. The daily dates are not runs; the short run is.
    entries = {i: [] for i in range(30)}
    for day in range(10):
        for i in range(day * 3, day * 3 + 3):
            entries[i] += [{"date": f"a{day}", "model": m} for m in "xy"]
    for run in range(4):
        for i in range(30):
            entries[i] += [{"date": f"b{run}", "model": m} for m in "xy" if not (run == 2 and m == "y" and i >= 13)]
    prompts = [{"id": f"p{i}", "entries": e} for i, e in entries.items()]
    assert bl.partial_runs(prompts) == [{"date": "b2", "model": "y", "count": 13, "typical": 30}]


def test_partial_runs_flags_a_missing_model_after_the_prompt_set_grew():
    # 20 prompts for 10 runs, then 60 for 3 runs; model y is missing from one of the later runs
    prompts = [{"id": f"p{i}", "entries": ([{"date": f"a{r}", "model": m} for r in range(10) for m in "xy"]
                                           if i < 20 else []) +
                [{"date": f"b{r}", "model": m} for r in range(3) for m in "xy" if not (r == 1 and m == "y")]}
               for i in range(60)]
    assert bl.partial_runs(prompts) == [{"date": "b1", "model": "y", "count": 0, "typical": 60}]


def test_partial_runs_flags_a_model_missing_from_a_run():
    prompts = [{"entries": [{"date": d, "model": m} for d in ("a", "b", "c") for m in ("x", "y")
                            if not (d == "b" and m == "y")]} for _ in range(5)]
    assert bl.partial_runs(prompts) == [{"date": "b", "model": "y", "count": 0, "typical": 5}]


def test_fanout_pages_and_sums_coverage_once_per_prompt():
    def page(queries, has_more, total=10):
        return {"data": {"queries": queries, "responseSummary": {"total": total, "captured": 2, "not_recorded": 8},
                         "typesPending": 1, "supportedModels": [{"model": "ChatGPT"}, {"model": "Gemini"}]},
                "pagination": {"limit": 2, "hasMore": has_more}}
    q = lambda n: {"promptId": "p1", "runId": "r3", "model": "ChatGPT", "query": f"q{n}", "sequence": n}
    routes = {
        (f"/brands/{BID}/prompts/p1/fanout-queries", 0): page([q(1), q(2)], True),
        (f"/brands/{BID}/prompts/p1/fanout-queries", 2): page([q(3)], False),
    }
    res = bl.fetch_fanout(FakeAPI(routes), BID, ["p1", "p-missing"], page_size=2)
    assert [x["query"] for x in res["queries"]] == ["q1", "q2", "q3"]
    assert res["coverage"] == {"total": 10, "captured": 2, "not_recorded": 8}
    assert res["typesPending"] == 1
    assert res["errors"] == ["p-missing"]


def test_compact_fanout_joins_each_search_to_its_run():
    raw = [{"id": "p1", "entries": [{"rid": "r3", "date": "2026-10-03", "model": "gpt-4o-mini", "hit": True},
                                    {"rid": "r9", "date": "2026-10-03", "model": "gemini-2.5-flash", "hit": False}]}]
    queries = [
        {"promptId": "p1", "runId": "r9", "model": "Gemini", "query": "b  query", "sequence": 1, "type": "howto",
         "kind": "search", "createdAt": "2026-10-03T01:00:00Z"},
        {"promptId": "p1", "runId": "r3", "model": "ChatGPT", "query": "a query", "sequence": 2, "type": None,
         "kind": "search", "createdAt": "2026-10-03T01:00:00Z"},
        {"promptId": "p1", "runId": "unknown", "model": "ChatGPT", "query": "c", "sequence": 1,
         "createdAt": "2026-10-04T02:00:00Z"},
    ]
    out = bl.compact_fanout(queries, raw)
    assert [(o["r"], o["m"], o["h"], o["d"], o["q"]) for o in out] == [
        ("r3", "gpt-4o-mini", True, "2026-10-03", "a query"),
        ("r9", "gemini-2.5-flash", False, "2026-10-03", "b query"),
        ("unknown", "gpt-4o-mini", None, "2026-10-04", "c"),
    ]


def test_render_escapes_data_and_fills_in_one_pass():
    template = "<script>const L=%%LABS%%;const R=%%RAW_HISTORY%%;</script><title>%%REPORT_TITLE%%</title>"
    brands = [{"key": "acme", "name": "Acme", "domain": "acme.pt"}]
    raw = {"x": "</script><!-- %%LABS%% <b>"}
    html = bl.render(template, brands, "A & B", {}, {}, {}, {}, {}, raw, {"k": 1})
    assert "</script><!--" not in html and "\\u003c/script>\\u003c!--" in html
    assert "%%LABS%%" in html  # text inside the data is left alone, not filled
    assert "<title>A &amp; B</title>" in html
    with pytest.raises(ValueError):
        bl.render(template + "%%ACTIONS%%", brands, "T", {}, {}, {}, {}, {}, {}, {})


def test_main_keeps_building_other_clients_when_one_fails(tmp_path, monkeypatch, capsys):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "a.json").write_text('{"brands": [{"id": "x", "name": "A", "key": "a", "domain": "a.pt"}],'
                                    ' "api_key_env": "NOT_SET_ANYWHERE"}', encoding="utf-8")
    (configs / "b.json").write_text('{"paused": true, "brands": []}', encoding="utf-8")
    monkeypatch.setattr(bl, "LABS_DIR", tmp_path)
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    built = []
    monkeypatch.setattr(bl, "build_report", lambda cfg, api, out: built.append(out))
    with pytest.raises(SystemExit) as exit_info:
        bl.main(["--all"])
    assert "1 labs report(s) failed: a" in str(exit_info.value)
    assert "b: paused" in capsys.readouterr().out and built == []
