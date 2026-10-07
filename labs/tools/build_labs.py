#!/usr/bin/env python3
"""
build_labs.py: builds the labs AI visibility reports, the test version of the
live reports at gregunik.github.io/ai-visibility/<slug>/.

Output: labs/<slug>/index.html, served at /ai-visibility/labs/<slug>/.
Production is untouched: configs/, .github/scripts/build_all.py and
refresh.yml keep cloning the upstream template on their own schedule.

Forked from filipelinsduarte/ai-visibility-report (build_fast.py and
template.html at upstream commit 0202dea, 2026-07-16). What changed:
  - no LLM code (production already runs with skip_nlp);
  - build_all.py's run-time patches are built in: offset paging for prompts,
    1.6 s pacing, UTF-8 config, no NLP;
  - archived prompts are left out, and each model's "latest result" is its
    most recent run (upstream kept the oldest: history arrives newest first);
  - new data: the official scores (visibility, share of voice, per-model
    scores, tracked competitors, daily timeseries, topics) and the fan-out
    searches ChatGPT and Gemini ran for each prompt
    (GET /brands/:id/prompts/:promptId/fanout-queries, not in the public docs);
  - data notes for the page: archived prompts, runs with a missing model,
    prompts at the 100-run history cap, failed endpoints.

Usage:
  python labs/tools/build_labs.py --all
  python labs/tools/build_labs.py --config labs/configs/credibom.json
  python labs/tools/build_labs.py --config ... --fixtures DIR --out FILE
"""

import argparse
import json
import os
import pathlib
import re
import statistics
import sys
import threading
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

BASE_URL = os.environ.get("AIV_API_BASE") or "https://www.aipeekaboo.com/api/v1"
TOOLS = pathlib.Path(__file__).resolve().parent
LABS_DIR = TOOLS.parent
TEMPLATE = TOOLS / "template.html"
WINDOW = "90d"


# ─── API clients ──────────────────────────────────────────────────────────────

class ApiError(RuntimeError):
    pass


class TrackerAPI:
    """GET client with one pace shared by every thread: the API counts each call."""

    def __init__(self, api_key, min_interval=1.6, retries=5, timeout=60):
        import requests  # imported here so the tests run without it
        self._session = requests.Session()
        self.api_key = api_key
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self.calls = 0
        self._lock = threading.Lock()
        self._last = 0.0

    def _pace(self):
        with self._lock:
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.calls += 1

    def get(self, path, params=None):
        last = "no attempt"
        for attempt in range(self.retries):
            self._pace()
            try:
                resp = self._session.get(BASE_URL + path, params=params, timeout=self.timeout,
                                         headers={"X-API-Key": self.api_key})
            except Exception as e:  # network blip: back off and retry
                last = f"{type(e).__name__}: {e}"
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code == 429:
                reset = resp.headers.get("X-RateLimit-Reset") or ""
                wait = min(120, max(1, int(reset) - int(time.time())) if reset.isdigit() else 60)
                print(f"    rate limited, waiting {wait}s", flush=True)
                last = "HTTP 429"
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                last = f"HTTP {resp.status_code}"
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise ApiError(f"GET {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                return resp.json()
            except ValueError:
                raise ApiError(f"GET {path} -> HTTP {resp.status_code} but not JSON: {resp.text[:120]}")
        raise ApiError(f"GET {path} failed after {self.retries} attempts ({last})")


class FixtureAPI:
    """Serves saved API responses from a folder, to build without a key."""

    ROUTES = [
        (re.compile(r"^/brands/[^/]+/prompts/([^/]+)/fanout-queries$"), "fanout-{0}.json"),
        (re.compile(r"^/brands/[^/]+/prompts/([^/]+)$"), "prompt-{0}.json"),
        (re.compile(r"^/brands/[^/]+/prompts$"), "prompts.json"),
        (re.compile(r"^/brands/[^/]+/visibility/timeseries$"), "timeseries.json"),
        (re.compile(r"^/brands/[^/]+/visibility/by-model$"), "by-model.json"),
        (re.compile(r"^/brands/[^/]+/visibility$"), "visibility.json"),
        (re.compile(r"^/brands/[^/]+/competitors$"), "competitors.json"),
        (re.compile(r"^/brands/[^/]+/categories$"), "categories.json"),
        (re.compile(r"^/brands/[^/]+/snapshot$"), "snapshot.json"),
    ]

    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        for pattern, name in self.ROUTES:
            m = pattern.match(path)
            if m:
                f = self.folder / name.format(*m.groups())
                if not f.exists():
                    raise ApiError(f"fixture missing: {f.name}")
                return json.loads(f.read_text(encoding="utf-8"))
        raise ApiError(f"no fixture route for {path}")


# ─── Classification helpers (verbatim from upstream build_fast.py) ────────────

DOMAIN_CAT_MAP = {
    "reddit.com": "Social Platform", "quora.com": "Social Platform", "linkedin.com": "Social Platform",
    "twitter.com": "Social Platform", "x.com": "Social Platform", "facebook.com": "Social Platform",
    "instagram.com": "Social Platform", "tiktok.com": "Social Platform", "pinterest.com": "Social Platform",
    "youtube.com": "Video Platform", "vimeo.com": "Video Platform", "dailymotion.com": "Video Platform",
    "g2.com": "Review Site", "capterra.com": "Review Site", "trustpilot.com": "Review Site",
    "producthunt.com": "Review Site", "yelp.com": "Review Site", "glassdoor.com": "Review Site",
    "tripadvisor.com": "Review Site", "trustradius.com": "Review Site", "getapp.com": "Review Site",
    "softwareadvice.com": "Review Site",
    "medium.com": "Publishing Platform", "substack.com": "Publishing Platform", "wordpress.com": "Publishing Platform",
    "github.com": "Developer Platform", "stackoverflow.com": "Developer Platform", "dev.to": "Developer Platform",
    "news.ycombinator.com": "Developer Platform",
    "apps.shopify.com": "eCommerce Platform", "shopify.com": "eCommerce Platform", "amazon.com": "eCommerce Platform",
    "amazon.co.uk": "eCommerce Platform", "etsy.com": "eCommerce Platform", "ebay.com": "eCommerce Platform",
    "techcrunch.com": "Tech News", "wired.com": "Tech News", "theverge.com": "Tech News", "venturebeat.com": "Tech News",
    "forbes.com": "Business News", "bloomberg.com": "Business News", "businessinsider.com": "Business News",
    "wsj.com": "Business News", "ft.com": "Business News", "economist.com": "Business News",
    "reuters.com": "News", "apnews.com": "News", "bbc.com": "News", "cnn.com": "News", "theguardian.com": "News",
}
_SOCIAL_DOMAINS = {"reddit.com", "quora.com", "twitter.com", "x.com", "linkedin.com", "facebook.com",
                   "instagram.com", "tiktok.com", "pinterest.com"}
_VIDEO_DOMAINS = {"youtube.com", "vimeo.com", "dailymotion.com"}
_PRODUCT_SEGS = ["/product/", "/products/", "/produto/", "/productos/", "/produkt/", "/produit/", "/produits/",
                 "/item/", "/items/", "/pd/", "/pdp/", "/buy/", "/shop/product", "/store/product"]
_PRODUCT_PATH_RE = re.compile(r"(?:/p[-_/][a-z0-9]|/-/p-|/_/[a-z]-p-|/dp/[a-z0-9]{8,}|/ref=[a-z]|/sku/[a-z0-9])",
                              re.IGNORECASE)
_PRODUCT_QUERY_RE = re.compile(r"[?&](productid|product_id|pid|ean|sku|itemid|item_id|variantid|variant_id)=",
                               re.IGNORECASE)
_CATEGORY_SEGS = ["/category/", "/categories/", "/categoria/", "/categorias/", "/collection/", "/collections/",
                  "/dept/", "/department/", "/departments/", "/browse/", "/shop/", "/store/",
                  "/sport/", "/sports/", "/desporto/", "/deporte/", "/esporte/", "/women/", "/men/", "/kids/",
                  "/children/", "/homme/", "/femme/", "/sale/", "/deals/", "/offers/", "/outlet/", "/promo/",
                  "/clothing/", "/shoes/", "/footwear/", "/accessories/", "/electronics/", "/home/", "/garden/",
                  "/furniture/", "/fitness/", "/outdoor/", "/running/", "/cycling/"]
_BLOG_SEGS = ["/blog/", "/articles/", "/article/", "/post/", "/posts/", "/editorial/", "/column/", "/columns/",
              "/insights/", "/resources/", "/resource/", "/learn/", "/education/", "/content/",
              "/thought-leadership/", "/perspectives/"]
_NEWS_SEGS = ["/news/", "/press/", "/press-release/", "/press-releases/", "/media/", "/media-center/",
              "/newsroom/", "/announcement/", "/announcements/"]
_DOC_SEGS = ["/docs/", "/doc/", "/documentation/", "/help/", "/support/", "/faq/", "/faqs/", "/knowledge-base/",
             "/kb/", "/manual/", "/getting-started/"]
_PRICING_SEGS = ["/pricing", "/plans", "/prices", "/tarifs", "/precos", "/preços"]
_REVIEW_SEGS = ["/review/", "/reviews/", "/ratings/", "/testimonials/", "/opinions/", "/avis/"]


def classify_domain(domain):
    if domain in DOMAIN_CAT_MAP:
        return DOMAIN_CAT_MAP[domain]
    for known, label in DOMAIN_CAT_MAP.items():
        if domain.endswith("." + known):
            return label
    if domain.endswith(".ai"):
        return "AI/SaaS"
    return "Industry Blog"


def classify_url(url, domain, title=""):
    title = (title or "").lower()
    path = urlparse(url).path.lower()
    query = urlparse(url).query.lower()
    t = title + " " + url.lower()
    if any(d in domain for d in _SOCIAL_DOMAINS):
        domain_type = "social_media"
    elif any(d in domain for d in _VIDEO_DOMAINS):
        domain_type = "video"
    elif any(seg in path for seg in _PRODUCT_SEGS) or _PRODUCT_PATH_RE.search(path) or _PRODUCT_QUERY_RE.search(query):
        domain_type = "product_page"
    elif any(seg in path for seg in _BLOG_SEGS):
        domain_type = "blog_article"
    elif any(seg in path for seg in _DOC_SEGS):
        domain_type = "documentation"
    elif any(seg in path for seg in _PRICING_SEGS):
        domain_type = "pricing_page"
    elif any(seg in path for seg in _NEWS_SEGS):
        domain_type = "news_article"
    elif any(seg in path for seg in _REVIEW_SEGS):
        domain_type = "review_page"
    elif any(seg in path for seg in _CATEGORY_SEGS):
        domain_type = "category_page"
    elif path in ("/", ""):
        domain_type = "homepage"
    elif path.count("/") <= 3:
        domain_type = "category_page"
    else:
        domain_type = "blog_article"

    if any(kw in t for kw in ["vs ", " versus ", "comparison", " alternative", "alternatives", "compare "]):
        content_type = "comparison"
    elif any(kw in t for kw in ["how to ", " guide", " tutorial", "step-by-step", "step by step"]):
        content_type = "how_to_guide"
    elif any(kw in t for kw in ["best ", "top ", " tools", " apps", " software", "ranked", "roundup", "top-"]):
        content_type = "listicle_roundup"
    elif any(kw in t for kw in [" review", " reviews", "tested", "hands-on", "hands on", "unboxing", " rating", " ratings"]):
        content_type = "product_review"
    elif any(kw in t for kw in ["case study", "success story", "customer story", "case-study"]):
        content_type = "case_study"
    elif any(kw in t for kw in [" report", " study", " survey", " research", " statistics", " stats"]):
        content_type = "research_report"
    elif any(kw in t for kw in ["press release", "press-release", "announces", "launches", "new launch"]):
        content_type = "press_release"
    else:
        content_type = {
            "social_media": "forum_thread", "video": "video", "product_page": "product_page",
            "category_page": "category_page", "news_article": "news_article", "review_page": "product_review",
            "pricing_page": "pricing_page", "documentation": "documentation", "homepage": "brand_homepage",
        }.get(domain_type, "blog_article")
    return domain_type, content_type


def extract_domain(url):
    try:
        domain = urlparse(url).netloc.lower()
        return domain[4:] if domain.startswith("www.") else domain
    except Exception:
        return url


def infer_intent(text):
    """Rule-based intent for prompts where the API returns none (upstream logic)."""
    t = text.lower()
    if re.search(r'\b(compar|vs\b|versus|alternat|review|difference between|instead of|better than|pros.and.cons)\b', t):
        return "INVESTIGATIONAL"
    if re.search(r'\b(buy|pric(e|ing|ed)|cost|purchas|sign.?up|get.started|free.trial|demo|subscri(be|ption))\b', t):
        return "TRANSACTIONAL"
    if re.search(r'\b(login|log.?in|sign.?in|homepage|official.site|download.app)\b', t):
        return "NAVIGATIONAL"
    if re.search(r'\b(best|top\s*\d*|leading|recommend|which\s.{1,60}(platform|tool|software|solution|system|service|app)|who\s(offers|provides|has))\b', t):
        return "COMMERCIAL"
    if re.search(r'\b(reddit|opinion|reputation|what.do.people|community|forum|feedback|think.of|experience.with)\b', t):
        return "SENTIMENT"
    return "INFORMATIONAL"


def normalize_comp_name(name):
    """Normalized competitor name for de-duplication ('Otterly AI' == 'otterly.ai').
    Accents don't count ('Hôma' == 'Homa'). Dropping words like 'Labs' and endings like
    '.com' can leave a generic stub: 'SEO Labs', 'SEO.com' and 'SEO' would all become
    'seo'. A result under 4 letters therefore keeps the name as written (letters and
    digits only), and those three stay apart."""
    name = _strip_accents(name)
    n = name.strip().lower()
    n = re.sub(r'\.(ai|com|io|co|org|net|app)$', '', n)
    n = re.sub(r'\s+ai$', '', n)
    n = re.sub(r'ai$', '', n)
    n = re.sub(r'\s+(digital|agency|media|platform|labs?|technologies?|solutions?)$', '', n)
    n = re.sub(r'[\s\-]', '', n)
    return n if len(n) >= 4 else _plain(name)


def _strip_accents(text):
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def comp_domain_from_name(name):
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    return slug + ".com"


def _brand_context(text, names, window=600):
    """A text window centred on the first of the brand's names (a name, or a list tried in
    order) found in the full response."""
    if not text:
        return ""
    idx = -1
    for name in ([names] if isinstance(names, str) else names):
        idx = text.find(name)
        if idx == -1 and len(name) > 4:  # 'ERA' must be written ERA, not the word 'era'
            idx = text.lower().find(name.lower())
        if idx != -1:
            break
    if idx == -1:
        return text[:window]
    start = max(0, idx - window // 3)
    end = min(len(text), idx + 2 * window // 3)
    excerpt = text[start:end].strip()
    return ("…" if start > 0 else "") + excerpt + ("…" if end < len(text) else "")


# ─── Prompts ──────────────────────────────────────────────────────────────────

def _pid(p):
    return p.get("promptId") or p.get("id")


def fetch_all_prompts(api, brand_id):
    """Every prompt of a brand. The API pages by offset (it ignores `page`)."""
    prompts, offset, limit = [], 0, 200
    while True:
        data = api.get(f"/brands/{brand_id}/prompts", {"limit": limit, "offset": offset})
        batch = data.get("prompts") or data.get("data") or []
        if not batch:
            break
        prompts.extend(batch)
        if not (data.get("pagination") or {}).get("hasMore"):
            break
        offset += limit
        if offset >= 10000:
            print("    warning: prompt paging stopped at 10,000", flush=True)
            break
    return prompts


def fetch_prompt_details(api, brand_id, prompt_ids, workers=4):
    def one(pid):
        try:
            return pid, api.get(f"/brands/{brand_id}/prompts/{pid}",
                                {"include_full_response": "true", "time_range": WINDOW})
        except ApiError as e:
            print(f"    warning: prompt {pid}: {e}", flush=True)
            return pid, None

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (pid, detail) in enumerate(ex.map(one, prompt_ids), 1):
            out[pid] = detail
            if i % 10 == 0 or i == len(prompt_ids):
                print(f"    prompt details {i}/{len(prompt_ids)}", flush=True)
    return out


def make_alias(brand_name, tracked_names, tracked_ids=None, brand_domain=""):
    """Map an entity from the answers to the name the report uses.

    - The API tags tracked competitors with a competitorId: that wins.
    - The brand's own variants ("Banco Credibom" for Credibom, "ERA Portugal" for ERA
      Imobiliaria on era.pt) map to None: they are the brand, not a competitor (the API
      sometimes types them "untracked"). See is_self_name. So does a word of the brand's
      name standing alone ("SEO" for UniK SEO): the category. See is_name_word.
    - Other spellings of a tracked competitor ("Cofidis Portugal", "Younited") map to
      the tracked name when their core names match (see same_name).
    Returns (alias, aliases): alias(name, competitor_id=None); aliases[name] = the other
    spellings seen, which the page needs to find those names inside fan-out searches.
    The brand's own names (brand_self_names) are always in aliases[brand_name].
    """
    tracked_ids = tracked_ids or {}
    aliases, cache = defaultdict(set), {}
    own = [n for n in brand_self_names(brand_name, brand_domain) if n != brand_name]
    if own:
        aliases[brand_name].update(own)

    def alias(name, competitor_id=None):
        if competitor_id and competitor_id in tracked_ids:
            canonical = tracked_ids[competitor_id]
            if name != canonical:
                aliases[canonical].add(name)
            return canonical
        if name not in cache:
            if is_self_name(name, brand_name, brand_domain):
                cache[name] = None
                if name != brand_name:
                    aliases[brand_name].add(name)
            elif is_name_word(name, brand_name):
                cache[name] = None  # the category ("SEO" for UniK SEO), not a competitor
            else:
                exact = next((t for t in tracked_names if normalize_comp_name(t) == normalize_comp_name(name)), None)
                cache[name] = exact or next((t for t in tracked_names if same_name(name, t)), name)
                if cache[name] != name:
                    aliases[cache[name]].add(name)
        return cache[name]

    return alias, aliases


def process_brand(api, brand, tracked_names=(), tracked_ids=None, max_failed_share=0.2):
    """Fetch and shape one brand's prompt data (upstream logic, see module notes)."""
    brand_id, brand_name, brand_domain = brand["id"], brand["name"], brand.get("domain", "")
    alias, aliases = make_alias(brand_name, tracked_names, tracked_ids, brand_domain)
    own_names = brand_self_names(brand_name, brand_domain)
    own_lower = {n.lower() for n in own_names}
    print(f"  prompts for {brand_name}...", flush=True)
    listed = fetch_all_prompts(api, brand_id)
    active = [p for p in listed if (p.get("status") or "active") == "active"]
    inactive = [p for p in listed if (p.get("status") or "active") != "active"]
    print(f"  {len(active)} active prompts, {len(inactive)} not active (left out)", flush=True)
    details = fetch_prompt_details(api, brand_id, [_pid(p) for p in active])
    missing = sum(1 for p in active if details.get(_pid(p)) is None)
    if active and missing > max_failed_share * len(active):
        # Publishing a page with most runs missing would replace the last good one.
        raise ApiError(f"{missing} of {len(active)} prompt details failed; keeping the previous page")

    prompts_out, all_citations, all_entities, sentiment_mentions, raw_prompt_history = [], [], [], [], []
    entity_types = defaultdict(set)
    capped, failed = [], []

    for p in active:
        prompt_id = _pid(p)
        prompt_text = p.get("promptText") or p.get("text") or ""
        search_intent = p.get("searchIntent") or infer_intent(prompt_text)
        topic = p.get("category") or ""
        detail = details.get(prompt_id)
        if detail is None:
            failed.append({"id": prompt_id, "text": prompt_text})
        body = (detail or {}).get("data") or detail or {}
        if (body.get("summary") or {}).get("truncated"):
            capped.append({"id": prompt_id, "text": prompt_text})
        # Newest first, so the first entry seen per model is its latest result.
        history = sorted(body.get("history") or [], key=lambda e: e.get("date") or "", reverse=True)

        models_data, scores, mentions_count, raw_entries = {}, [], 0, []
        for entry in history:
            model_key = entry.get("aiModel") or entry.get("model", "unknown")
            mentioned = bool(entry.get("mentioned", False))
            score = entry.get("score", 0) or 0
            rank = entry.get("rank")
            sentiment = (entry.get("sentiment") or "").lower() or None
            if sentiment and sentiment not in ("positive", "negative", "neutral", "uncertain"):
                sentiment = "neutral"
            response_text = entry.get("response") or entry.get("fullResponse") or entry.get("responseText") or ""
            brand_mentions = entry.get("brandMentions") or entry.get("entities") or []
            # Competitors named in this answer: canonical names, each counted once per answer.
            answer_comps, seen_in_answer = [], set()
            for ent in brand_mentions:
                ent_type = (ent.get("type") or ent.get("entityType") or "").lower()
                raw_name = ent.get("entityName") or ent.get("name", "")
                if ent_type not in ("competitor", "untracked") or not raw_name:
                    continue
                name = alias(raw_name, ent.get("competitorId"))
                if name and normalize_comp_name(name) not in seen_in_answer:
                    seen_in_answer.add(normalize_comp_name(name))
                    answer_comps.append(name)
                    entity_types[name].add(ent_type)

            if model_key not in models_data:
                models_data[model_key] = {"mentioned": mentioned, "score": score, "rank": rank,
                                          "sentiment": sentiment, "snippet": response_text[:300]}
            reason = ""
            if mentioned:
                mentions_count += 1
                scores.append(score)
                reason = next((b.get("mentionSummary", "") for b in brand_mentions
                               if (b.get("entityName") or "").lower() in own_lower),
                              entry.get("mentionSummary", "") or entry.get("sentimentReason") or "")[:400]
                if sentiment:
                    full_resp = entry.get("fullResponse") or response_text
                    sentiment_mentions.append({
                        "prompt": prompt_text, "model": model_key, "rank": rank, "score": score,
                        "sentiment": sentiment, "reason": reason,
                        "context": _brand_context(full_resp, own_names, 600) or response_text[:400],
                        "competitors": list(answer_comps),
                    })

            raw_srcs = []
            for src in entry.get("sources") or entry.get("citedSources") or []:
                url = src.get("url", "")
                if not url:
                    continue
                title = src.get("title") or urlparse(url).path or url
                all_citations.append((url, title, model_key))
                pt, ct = classify_url(url, extract_domain(url), title)
                raw_srcs.append({"u": url, "t": title[:100], "pt": pt, "ct": ct})

            for name in answer_comps:
                all_entities.append((name, "competitor", model_key))
            raw_comps = list(answer_comps)

            raw_entries.append({
                "date": entry.get("date", ""), "model": model_key, "rid": entry.get("runId"),
                "hit": mentioned, "sc": score, "rk": rank, "snt": sentiment, "rsn": reason,
                "ctx": (_brand_context(entry.get("fullResponse") or response_text, own_names, 600)
                        or (entry.get("responseSnippet") or "")[:400]) if mentioned else "",
                "srcs": raw_srcs, "comps": raw_comps,
            })

        raw_prompt_history.append({"id": prompt_id, "text": prompt_text, "intent": search_intent,
                                   "topic": topic, "entries": raw_entries})
        prompts_out.append({
            "id": prompt_id, "text": prompt_text, "intent": search_intent, "topic": topic,
            "avgScore": round(sum(scores) / len(scores), 2) if scores else 0.0,
            "bestScore": max(scores) if scores else 0, "mentions": mentions_count,
            "totalRuns": len(history), "models": models_data,
        })

    # ── Citations ──
    url_data = {}
    for url, title, model_key in all_citations:
        info = url_data.setdefault(url, {"title": title, "count": 0, "models": set(), "mc": defaultdict(int)})
        info["count"] += 1
        info["models"].add(model_key)
        info["mc"][model_key] += 1

    domain_counts, domain_url_list = defaultdict(int), defaultdict(list)
    domain_type_counts, content_type_counts = defaultdict(int), defaultdict(int)
    url_cache, dcat = {}, {}
    for url, info in url_data.items():
        domain = extract_domain(url)
        dt, ct = classify_url(url, domain, info["title"])
        url_cache[url] = (domain, dt, ct)
        domain_counts[domain] += info["count"]
        dcat[domain] = classify_domain(domain)
        domain_type_counts[dt] += info["count"]
        content_type_counts[ct] += info["count"]
        domain_url_list[domain].append({"url": url, "title": info["title"], "count": info["count"],
                                        "models": sorted(info["models"]), "mc": dict(info["mc"]),
                                        "pageType": dt, "contentType": ct})

    by_count = lambda d: sorted(d.items(), key=lambda x: -x[1])
    top_listicles = sorted(
        ({"domain": dom, "url": u["url"], "title": u["title"], "count": u["count"]}
         for dom, urls in domain_url_list.items() for u in urls if u["contentType"] == "listicle_roundup"),
        key=lambda x: -x["count"])[:10]
    citations_out = {
        "total": sum(i["count"] for i in url_data.values()),
        "uniqueUrls": len(url_data), "uniqueDomains": len(domain_counts),
        "domainTypes": [{"type": k, "count": v} for k, v in by_count(domain_type_counts)],
        "contentTypes": [{"type": k, "count": v} for k, v in by_count(content_type_counts)],
        "topDomains": [{"domain": d, "count": c} for d, c in by_count(domain_counts)[:20]],
        "topListicles": top_listicles,
    }
    durl_brand = {d: sorted(domain_url_list[d], key=lambda x: -x["count"])[:12]
                  for d, _ in by_count(domain_counts)[:40]}

    # ── Sentiment ──
    sent_counts = {"positive": 0, "neutral": 0, "negative": 0, "uncertain": 0}
    for m in sentiment_mentions:
        sent_counts[m.get("sentiment") or "neutral"] += 1
    sentiment_out = {"total_mentions": len(sentiment_mentions), **sent_counts, "mentions": sentiment_mentions}

    # ── Citations per model ──
    model_cit = defaultdict(lambda: {"total": 0, "domains": defaultdict(int),
                                     "domain_types": defaultdict(int), "content_types": defaultdict(int)})
    for url, title, model_key in all_citations:
        domain, dt, ct = url_cache[url]
        mc = model_cit[model_key]
        mc["total"] += 1
        mc["domains"][domain] += 1
        mc["domain_types"][dt] += 1
        mc["content_types"][ct] += 1
    model_citations_out = {
        mk: {"total": i["total"], "uniqueDomains": len(i["domains"]),
             "topDomains": [{"domain": d, "count": c} for d, c in by_count(i["domains"])[:10]],
             "domainTypes": [{"type": k, "count": v} for k, v in by_count(i["domain_types"])],
             "contentTypes": [{"type": k, "count": v} for k, v in by_count(i["content_types"])]}
        for mk, i in model_cit.items()
    }

    # ── Competitor names: one canonical spelling per normalized name ──
    norm_groups = defaultdict(list)
    for name, _, _ in all_entities:
        norm_groups[normalize_comp_name(name)].append(name)
    name_to_canonical = {}
    for names in norm_groups.values():
        counts = Counter(names)
        canonical = max(counts, key=lambda n: (counts[n], n[0].isupper(), "." not in n,
                                               not n.lower().endswith(".ai"), len(n)))
        for n in counts:
            name_to_canonical[n] = canonical

    comp_data = defaultdict(lambda: {"mentions": 0, "models": set(), "model_counts": defaultdict(int)})
    for name, _, model_key in all_entities:
        c = comp_data[name_to_canonical.get(name, name)]
        c["mentions"] += 1
        c["models"].add(model_key)
        c["model_counts"][model_key] += 1
    competitors_out = sorted(({"name": n, "mentions": i["mentions"], "avgScore": 0, "topSentiment": "neutral",
                               "models": sorted(i["models"]), "modelMentions": dict(i["model_counts"]),
                               "summaries": []} for n, i in comp_data.items()), key=lambda x: -x["mentions"])
    comp_domains = {c["name"]: comp_domain_from_name(c["name"]) for c in competitors_out}

    def canon(names):  # canonical spellings, each once
        return list(dict.fromkeys(name_to_canonical.get(c, c) for c in names))

    for rp in raw_prompt_history:
        for e in rp["entries"]:
            e["comps"] = canon(e["comps"])
    for sm in sentiment_mentions:
        sm["competitors"] = canon(sm["competitors"])
    canonical_types = defaultdict(set)
    for name, types in entity_types.items():
        canonical_types[name_to_canonical.get(name, name)] |= types

    run_dates = sorted({e["date"] for rp in raw_prompt_history for e in rp["entries"] if e.get("date")})
    return {
        "prompts": prompts_out, "citations": citations_out, "competitors": competitors_out,
        "sentiment": sentiment_out, "modelCitations": model_citations_out,
        "durl": durl_brand, "dcat": dcat, "comp_domains": comp_domains,
        "raw_history": {"runDates": run_dates, "prompts": raw_prompt_history},
        "entity_types": {k: sorted(v) for k, v in canonical_types.items()},
        "aliases": {k: sorted(v) for k, v in aliases.items()},
        "inactive": [{"id": _pid(p), "text": p.get("promptText") or p.get("text") or "",
                      "status": p.get("status") or ""} for p in inactive],
        "capped": capped, "failed": failed,
    }


# ─── Official scores ───────────────────────────────────────────────────

OFFICIAL_ENDPOINTS = [
    ("visibility", "/visibility", {"time_range": WINDOW}),
    ("byModel", "/visibility/by-model", {"time_range": WINDOW}),
    ("competitors", "/competitors", {"time_range": WINDOW}),
    ("timeseries", "/visibility/timeseries", {"time_range": WINDOW, "include_competitors": "true"}),
    ("snapshot", "/snapshot", None),
]


def fetch_official(api, brand_id):
    """Brand-level endpoints. A failure here costs a card, never the report."""
    out, failed = {}, []
    for key, suffix, params in OFFICIAL_ENDPOINTS:
        try:
            body = api.get(f"/brands/{brand_id}{suffix}", params)
            out[key] = body.get("data") if isinstance(body, dict) else None
        except ApiError as e:
            print(f"    warning: {key}: {e}", flush=True)
            out[key] = None
            failed.append(key)
    snapshot = out.pop("snapshot") or {}
    out["traffic"] = snapshot.get("traffic") if isinstance(snapshot, dict) else None
    if isinstance(out.get("visibility"), dict):
        out["visibility"].pop("topPrompts", None)
    return out, failed


# Words that don't identify a company: markets, legal forms, the sector itself.
GENERIC_NAME_WORDS = {
    "portugal", "pt", "españa", "espana", "spain", "es", "online", "sa", "group", "grupo",
    "bank", "banco", "credit", "crédito", "credito", "finance", "financeira", "financial",
    "ltd", "inc", "plc", "de", "da", "do", "of", "the", "y", "e",
}


def name_core(name):
    """The identifying words of a company name, accents dropped
    ('Banco Cofidis Portugal' -> ('cofidis',), 'Cételem' -> ('cetelem',))."""
    return tuple(w for w in re.split(r"[^\w]+", _strip_accents(name.lower())) if w and w not in GENERIC_NAME_WORDS)


def same_name(a, b):
    """Two spellings of one company: equal once normalized, or equal identifying words.
    'Cofidis Portugal' = 'Cofidis', 'Younited' = 'Younited Credit', 'Oney Bank' = 'Oney';
    but 'Santander' != 'Santander Consumer Finance', 'Caixa' != 'Caixa Geral de Depósitos'
    and 'SEO' != 'SEO Labs'. The page uses the same rule (_sameName in template.html)."""
    if normalize_comp_name(a) == normalize_comp_name(b):
        return True
    core_a = name_core(a)
    return bool(core_a) and core_a == name_core(b)


def _fold(text):
    """Letters and digits only, lowercase, no accents: 'El Corte Inglés' -> 'elcorteingles'."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if ch.isalnum())


def base_name(name):
    """The configured name without its market label: 'WiZink (España)' -> 'WiZink'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() or name


_SECOND_LEVEL = {"com", "co", "org", "net", "gov", "edu", "ac", "nom", "gob", "mil"}


def domain_stem(domain):
    """The name part of a domain, folded: 'unik-seo.com' -> 'unikseo', 'www.era.pt' -> 'era',
    'foo.com.pt' -> 'foo', 'app.n26.com' -> 'n26'."""
    host = re.sub(r"^https?://", "", (domain or "").strip().lower()).split("/")[0]
    labels = [x for x in host.split(".") if x and x != "www"]
    if len(labels) < 2:
        return _fold(labels[0]) if labels else ""
    return _fold(labels[-3] if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL else labels[-2])


def brand_self_names(name, domain=""):
    """The brand's own names as text writes them: the configured name, the name without its
    market label ('El Corte Inglés' for 'El Corte Inglés (Casa)') and the leading words
    that spell its domain ('ERA' for 'ERA Imobiliaria' on era.pt)."""
    base = base_name(name)
    out = [name, base]
    stem, words = domain_stem(domain), base.split()
    for k in range(1, len(words) + 1):
        if stem and _fold(" ".join(words[:k])) == stem:
            out.append(" ".join(words[:k]))
            break
    return list(dict.fromkeys(out))


def _plain(name):
    return re.sub(r"[\W_]+", "", _strip_accents(name).lower())


def is_name_word(name, brand_name):
    """A word of the client's own name standing alone: 'SEO' for 'UniK SEO', 'Imobiliaria'
    for 'ERA Imobiliaria'. The AIs use it for the category, so it is not a competitor."""
    words = base_name(brand_name).split()
    return len(words) > 1 and _plain(name) in {_plain(w) for w in words}


def is_self_name(name, brand_name, domain=""):
    """A spelling of the brand itself: same_name as one of its own names, or a name whose
    identifying words spell its domain ('ERA Portugal' on era.pt, 'Adelante Shoes' on
    adelanteshoes.com)."""
    if any(same_name(name, n) for n in brand_self_names(brand_name, domain)):
        return True
    stem = domain_stem(domain)
    return bool(stem) and stem in (_fold(name), _fold(" ".join(name_core(name))))


def tracked_competitors(official_competitors, entity_types):
    """Tracked competitor names, spelled as in the mention data, plus the tracked list itself."""
    api_names = [c["name"] for c in ((official_competitors or {}).get("competitors") or []) if c.get("name")]
    tracked = {n for n, types in entity_types.items()
               if "competitor" in types or any(same_name(n, t) for t in api_names)}
    return sorted(tracked | set(api_names), key=str.lower)


def tracked_domains(official_competitors, names):
    """Real domains for tracked competitors (favicons), keyed by every spelling in `names`."""
    domains = [(c["name"], extract_domain(c["url"]).rstrip("/"))
               for c in ((official_competitors or {}).get("competitors") or []) if c.get("name") and c.get("url")]
    out = {}
    for n in names:
        match = next((dom for t, dom in domains if same_name(n, t)), None)
        if match:
            out[n] = match
    return out


# ─── Fan-out searches ─────────────────────────────────────────────────────────

def fetch_fanout(api, brand_id, prompt_ids, page_size=200):
    """Every recorded fan-out search for each prompt, over the default 90-day window."""
    res = {"queries": [], "coverage": Counter(), "typesPending": 0, "errors": [], "truncated": [],
           "supported": [], "window": None}
    for pid in prompt_ids:
        offset = 0
        while True:
            try:
                d = api.get(f"/brands/{brand_id}/prompts/{pid}/fanout-queries",
                            {"limit": page_size, "offset": offset})
            except ApiError as e:
                print(f"    warning: fan-out {pid}: {e}", flush=True)
                res["errors"].append(pid)
                break
            data = (d.get("data") if isinstance(d, dict) else None) or {}
            if offset == 0:
                for k, v in (data.get("responseSummary") or {}).items():
                    if isinstance(v, int):
                        res["coverage"][k] += v
                res["typesPending"] += data.get("typesPending") or 0
                if data.get("truncated"):
                    res["truncated"].append(pid)
                if not res["supported"]:
                    res["supported"] = data.get("supportedModels") or []
                if not res["window"] and data.get("window"):
                    res["window"] = data["window"]
            for q in data.get("queries") or []:
                q.setdefault("promptId", pid)
                res["queries"].append(q)
            page = d.get("pagination") or {}
            if not page.get("hasMore"):
                break
            offset += page.get("limit") or page_size
            if offset >= 5000:
                res["truncated"].append(pid)
                break
    res["coverage"] = dict(res["coverage"])
    return res


def model_key_map(raw_prompts):
    """Fan-out names models by label (ChatGPT, Gemini); the history uses model keys."""
    keys = sorted({e["model"] for p in raw_prompts for e in p["entries"]})

    def pick(prefixes, fallback):
        return next((k for k in keys if k.lower().startswith(prefixes)), fallback)

    return {"chatgpt": pick(("gpt", "chatgpt", "openai", "o1", "o3", "o4"), "gpt-4o-mini"),
            "gemini": pick(("gemini",), "gemini-2.5-flash")}


def compact_fanout(queries, raw_prompts):
    """One small record per search, joined to its run: date, model key, brand mentioned."""
    runs = {e["rid"]: (e["date"], e["model"], e["hit"])
            for p in raw_prompts for e in p["entries"] if e.get("rid")}
    kmap = model_key_map(raw_prompts)
    out = []
    for q in queries:
        rid = q.get("runId")
        date, mkey, hit = runs.get(rid, (None, None, None))
        label = (q.get("model") or "").strip().lower()
        out.append({"p": q.get("promptId"), "r": rid, "m": mkey or kmap.get(label, label),
                    "q": re.sub(r"\s+", " ", q.get("query") or "").strip(), "s": q.get("sequence") or 0,
                    "k": q.get("kind"), "t": q.get("type"),
                    "d": date or (q.get("createdAt") or "")[:10], "h": hit})
    out.sort(key=lambda x: (x["p"] or "", x["d"], x["r"] or "", x["s"]))
    return out


# ─── Data notes ───────────────────────────────────────────────────────────────

def partial_runs(raw_prompts, threshold=0.7, capped_ids=()):
    """Runs where a model answered far fewer prompts than usual (0 = missing entirely).

    Only run dates are checked: dates on which some model answered at least half of
    the prompts. A brand that runs a few prompts a day (Adelante until September) has
    dates that are not runs. Only run dates between a model's first and last answer
    are checked: a model added later, or dropped, is not a gap in a run. Prompts at
    the 100-run history cap lose their oldest runs part-way through a date, so dates
    older than the newest "oldest kept date" among capped prompts are not checked either.
    """
    capped_ids = set(capped_ids)
    floor = max((min((e["date"] for e in p["entries"] if e.get("date")), default="")
                 for p in raw_prompts if p.get("id") in capped_ids), default="")
    counts, answered = defaultdict(Counter), 0
    for p in raw_prompts:
        dated = [e for e in p["entries"] if e.get("date") and e["date"] >= floor]
        for e in dated:
            counts[e["date"]][e["model"]] += 1
        answered += bool(dated)
    dates = sorted(counts)
    if floor and dates and dates[0] == floor:
        dates = dates[1:]  # the floor date itself is partial for the capped prompts
    dates = [d for d in dates if max(counts[d].values()) >= 0.5 * answered]
    models = sorted({m for d in dates for m in counts[d]})
    notes = []
    for m in models:
        series = [counts[d][m] for d in dates]
        nonzero = [n for n in series if n > 0]
        if not nonzero:
            continue
        typical = statistics.median(nonzero)
        first = next(i for i, n in enumerate(series) if n > 0)
        last = max(i for i, n in enumerate(series) if n > 0)
        for d, n in list(zip(dates, series))[first:last + 1]:
            if n < threshold * typical:
                notes.append({"date": d, "model": m, "count": n, "typical": int(round(typical))})
    return sorted(notes, key=lambda x: (x["date"], x["model"]))


# ─── Page ─────────────────────────────────────────────────────────────────────

def brand_toggle_html(brands):
    parts = []
    for i, b in enumerate(brands):
        cls = "bt-btn active" if i == 0 else "bt-btn"
        key_safe = b["key"].replace("'", "\\'")
        parts.append(f'<button class="{cls}" onclick="setBrand(\'{key_safe}\',this)">'
                     f'<img src="https://www.google.com/s2/favicons?domain={b["domain"]}&sz=32" '
                     f'onerror="this.style.display=\'none\'">{b["name"]}</button>')
    return "".join(parts)


def js(obj):
    """JSON for an inline <script>. Every '<' becomes \\u003c (valid inside JSON strings, the
    only place it can appear), so data can never close the tag or open a comment."""
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def render(template_text, brands, title, D, DURL, DCAT, COMP, BRAND_CFG, RAW, LABS):
    """Fill the template's placeholders in one pass, so data can't be mistaken for one."""
    import html as _html
    replacements = {
        "REPORT_TITLE": _html.escape(title), "BRAND_TOGGLE": brand_toggle_html(brands),
        "DATA": js(D), "DOMAIN_URLS": js(DURL), "DOMAIN_CATEGORIES": js(DCAT),
        "COMP_DOMAINS": js(COMP), "BRAND_CFG": js(BRAND_CFG),
        "DEFAULT_BRAND": brands[0]["key"], "RAW_HISTORY": js(RAW), "LABS": js(LABS),
    }
    unknown = sorted(set(re.findall(r"%%([A-Z_]+)%%", template_text)) - set(replacements))
    if unknown:
        raise ValueError(f"template has placeholders the builder does not fill: {unknown}")
    return re.sub(r"%%([A-Z_]+)%%", lambda m: replacements[m.group(1)], template_text)


def build_report(cfg, api, out_path, template_path=TEMPLATE):
    brands = cfg["brands"]
    D = {"prompts": {}, "citations": {}, "competitors": {}, "sentiment": {}, "modelCitations": {}}
    DURL, DCAT, COMP, BRAND_CFG, RAW, LABS = {}, {}, {}, {}, {}, {}

    for b in brands:
        name, key = b["name"], b["key"]
        print(f"\n== {name}", flush=True)
        print("  official scores...", flush=True)
        official, failed = fetch_official(api, b["id"])
        api_list = [c for c in ((official.get("competitors") or {}).get("competitors") or []) if c.get("name")]
        data = process_brand(api, b, [c["name"] for c in api_list],
                             {c["id"]: c["name"] for c in api_list if c.get("id")})
        raw_prompts = data["raw_history"]["prompts"]
        print(f"  fan-out searches for {len(raw_prompts)} prompts...", flush=True)
        fan = fetch_fanout(api, b["id"], [p["id"] for p in raw_prompts])
        queries = compact_fanout(fan["queries"], raw_prompts)
        kmap = model_key_map(raw_prompts)
        fan_models = sorted({kmap.get((s.get("model") or "").lower(), (s.get("model") or "").lower())
                             for s in fan["supported"]} | {q["m"] for q in queries})
        print(f"  {len(queries)} fan-out searches; coverage {fan['coverage']}", flush=True)

        tracked = tracked_competitors(official.get("competitors"), data["entity_types"])
        names = [c["name"] for c in data["competitors"]] + tracked
        domains = tracked_domains(official.get("competitors"), names)

        D["prompts"][name] = data["prompts"]
        D["citations"][name] = data["citations"]
        D["competitors"][name] = data["competitors"]
        D["sentiment"][name] = data["sentiment"]
        D["modelCitations"][name] = data["modelCitations"]
        DURL[name] = data["durl"]
        DCAT.update(data["dcat"])
        COMP.update(data["comp_domains"])
        COMP.update(domains)
        BRAND_CFG[key] = {"key": name, "name": name, "url": b["domain"]}
        RAW[key] = data["raw_history"]
        LABS[key] = {
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "official": official,
            "tracked": tracked,
            "aliases": data["aliases"],
            "fanout": {
                "queries": queries,
                "models": fan_models,
                "coverage": fan["coverage"],
                "typesPending": fan["typesPending"],
                "firstDate": min((q["d"] for q in queries if q["d"]), default=None),
                "window": fan["window"],
                "prompts": len(raw_prompts),
                "errors": fan["errors"],
                "truncated": fan["truncated"],
            },
            "notes": {
                "inactive": data["inactive"],
                "partialRuns": partial_runs(raw_prompts, capped_ids=[c["id"] for c in data["capped"]]),
                "capped": data["capped"],
                "failedPrompts": data["failed"],
                "failedEndpoints": failed,
            },
        }

    title = cfg.get("report_title") or "AI Visibility Report (labs): " + " & ".join(b["name"] for b in brands)
    html = render(pathlib.Path(template_path).read_text(encoding="utf-8"), brands, title,
                  D, DURL, DCAT, COMP, BRAND_CFG, RAW, LABS)
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\n  wrote {out_path} ({len(html) / 1e6:.1f} MB, {api.calls} API calls)", flush=True)


def _api_for(cfg, fixtures):
    if fixtures:
        return FixtureAPI(fixtures)
    env = cfg.get("api_key_env", "AIV_API_KEY")
    key = os.environ.get(env, "")
    if not key:
        raise ApiError(f"{env} is not set")  # this client fails, the others still build
    return TrackerAPI(key)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--config", help="one labs config (JSON)")
    ap.add_argument("--all", action="store_true", help="every config in labs/configs/")
    ap.add_argument("--out", help="output HTML (default labs/<slug>/index.html)")
    ap.add_argument("--fixtures", help="folder of saved API responses (no key needed)")
    args = ap.parse_args(argv)

    if args.all:
        configs = sorted((LABS_DIR / "configs").glob("*.json"))
    elif args.config:
        configs = [pathlib.Path(args.config)]
    else:
        ap.error("give --config or --all")

    failures = []
    for path in configs:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if cfg.get("paused"):
            print(f"{path.stem}: paused, skipped ({cfg.get('paused_reason', 'no reason given')})")
            continue
        out = pathlib.Path(args.out) if args.out and not args.all else LABS_DIR / path.stem / "index.html"
        try:
            build_report(cfg, _api_for(cfg, args.fixtures), out)
        except Exception as e:  # one client's failure must not stop the others
            print(f"FAILED {path.stem}: {type(e).__name__}: {e}", flush=True)
            failures.append(path.stem)
    if failures:
        sys.exit(f"{len(failures)} labs report(s) failed: {', '.join(failures)}")


if __name__ == "__main__":
    main()
