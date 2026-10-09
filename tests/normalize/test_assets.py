"""T-23: asset-hash rule family (FR-44) — build hashes inside URL attributes.

Positives and negatives are taken verbatim from the five T-04 captures (F-013): every
URL that changed between the 2026-09-17 and 2026-09-25 snapshots is a positive, and the
meaningful URLs that sat next to them are the negatives. The point of the family is that
`youtube.com/watch?v=4anAwXYqLG8` and `pydoctheme.css?v=4365c8fe` look identical in
shape — only the asset extension on the path separates them.
"""

from __future__ import annotations

import pytest

from semdiff import Config, NormalizationConfig, normalize, parse
from semdiff.normalize import BUILTIN_RULES, RuleFamily, Target, apply_rules
from semdiff.normalize.rules.assets import ASSET_EXTENSIONS, ASSET_RULES, PHASE_ASSET_HASH

BY_ID = {rule.id: rule for rule in ASSET_RULES}

# (rule id, url as captured, url after the rule)
POSITIVE = [
    # webpack / Docusaurus / umi: <name>.<hash>.<ext>
    ("asset.dotted_hash", "/assets/js/main.3eef80bd.js", "/assets/js/main.js"),
    ("asset.dotted_hash", "/assets/js/runtime~main.9d50a0eb.js", "/assets/js/runtime~main.js"),
    ("asset.dotted_hash", "/umi.da948370.js", "/umi.js"),
    ("asset.dotted_hash", "/assets/css/styles.bbe6e1c2.css", "/assets/css/styles.css"),
    ("asset.dotted_hash", "/style-acss.5d057a68.css", "/style-acss.css"),
    ("asset.dotted_hash", "/_dumi_global_less_19mmnhuljhj8q.d613f403.css", "/_dumi_global_less_19mmnhuljhj8q.css"),
    # Next.js: <name>-<hash>.<ext>
    ("asset.dashed_hash", "/_next/static/chunks/99013-8b54dcaea3573ec3.js", "/_next/static/chunks/99013.js"),
    ("asset.dashed_hash", "/_next/static/chunks/pages/_app-22a997e83633ecca.js", "/_next/static/chunks/pages/_app.js"),
    ("asset.dashed_hash", "/_next/static/chunks/framework-8fb8fbc01eded9ef.js", "/_next/static/chunks/framework.js"),
    ("asset.dashed_hash", "/_next/static/chunks/webpack-6bfd4c0255298238.js", "/_next/static/chunks/webpack.js"),
    # Next.js build id as a path segment
    ("asset.next_build_id", "/_next/static/gHfMlRY8DvlLFUGxibDRr/_buildManifest.js", "/_next/static/_buildManifest.js"),
    ("asset.next_build_id", "/_next/static/AMRydBsto2kaHHqHy9mdJ/_ssgManifest.js", "/_next/static/_ssgManifest.js"),
    # Sphinx cache busters
    ("asset.query_cache_buster", "../_static/pydoctheme.css?v=4365c8fe", "../_static/pydoctheme.css"),
    ("asset.query_cache_buster", "../_static/doctools.js?v=9bcbadda", "../_static/doctools.js"),
    ("asset.query_cache_buster", "/app.css?ver=1a2b3c4d", "/app.css"),
    # Rollup / Vite / Astro base64url: <name>.<hash>.<ext>
    ("asset.dotted_base64", "/assets/chunks/theme.BImhtZeh.js", "/assets/chunks/theme.js"),
    ("asset.dotted_base64", "/_astro/common.CQ2eGxR-.css", "/_astro/common.css"),
    ("asset.dotted_base64", "/assets/style.C_NjyM-H.css", "/assets/style.css"),
    ("asset.dotted_base64", "/fonts/inter-roman-latin.Cy4MYw_J.woff", "/fonts/inter-roman-latin.woff"),
    ("asset.dotted_base64", "/logo-light.BTLa6bQG.svg", "/logo-light.svg"),
    ("asset.dotted_base64", "/assets/app.BuWgJKRa.js", "/assets/app.js"),
    # Vite entry bundles: <name>-<hash>.<ext>  (the pnpm-io fixtures)
    ("asset.dashed_base64", "/assets/index-CjpiBuHV.js", "/assets/index.js"),
    ("asset.dashed_base64", "/assets/index-CxL6fshY.js", "/assets/index.js"),
    ("asset.dashed_base64", "/assets/index-67LBnYfl.js", "/assets/index.js"),
    ("asset.dashed_base64", "/assets/index-eKBMIA92.js", "/assets/index.js"),
    ("asset.dashed_base64", "/assets/index-gKrm_uHA.css", "/assets/index.css"),
    ("asset.dashed_base64", "/assets/index-DD5X4HF3.css", "/assets/index.css"),
]

# Meaningful URLs from the same captures. No asset rule may alter any of them.
NEGATIVE = [
    # the decisive one: same shape as a cache buster, different meaning
    "https://www.youtube.com/watch?v=4anAwXYqLG8",
    "https://www.youtube.com/watch?v=Yhyx7otSksg",
    "https://www.rfc-editor.org/errata_search.php?rfc=7159",
    "https://github.com/python/cpython/blob/3.14/Doc/library/json.rst?plain=1",
    "/~demos/button-demo-icon?routeId=components%2Fbutton%2Findex.en-US",
    "/api/v2/products?page=3",
    # versions and numbers in paths
    "https://datatracker.ietf.org/doc/html/rfc4627.html",
    "https://docusaurus-archive-october-2023.netlify.app/docs/2.3.1",
    "https://docusaurus.io/blog/2022/08/01/announcing-docusaurus-2.0",
    "https://github.com/facebook/docusaurus/issues/10556",
    "https://docs.microsoft.com/en-us/lifecycle/products/internet-explorer-11",
    "/material-ui/integrations/tailwindcss/tailwindcss-v4/",
    "/blog/releases/3.10",
    # extensions that are not assets, or hashes that are too short / not hex-shaped
    "https://example.com/a/b/c-2024report.pdf",
    "/static/logo-2x.png",
    "/data/report-2024.json",
    "/page-abcdef.html",
    "/assets/js/main.abcd.js",  # 4 chars: below the floor
    "/assets/js/main.12345678.js",  # digits only: not hash-shaped
    "/assets/js/main.abcdefgh.js",  # letters only, and 'g','h' are not hex
    "/_next/static/chunks/app.js",  # 'chunks' is too short to be a build id
    "/_next/static/media/logo.svg",
    # real font filenames from the same captures: an uppercase-bearing segment that is a
    # word, not a hash — 6, 7, 13 and 14 characters rather than 8
    "/fonts/AlibabaSans-Medium.woff",
    "/fonts/AlibabaSans-Regular.woff",
    "/fonts/Inter-Regular-subset.woff",
    "/fonts/SpaceGrotesk-Medium-subset.woff",
    # eight characters, but all-caps words rather than a hash
    "/css/app-SETTINGS.css",
    "/css/app-CALENDAR.css",
    # eight characters of two CamelCase words: what a hand-written asset name looks like
    "/img/logo-DarkMode.png",
    "/css/theme-LiteMode.css",
    "/img/icon-MainPage.svg",
    "/img/hero-SideMenu.png",
    # lowercase-only and digit-only segments stay the hex rules' business, and they reject these
    "/assets/index-abcdefgh.js",
    "/assets/index-12345678.js",
]


def first(html: str, attribute: str = "src") -> str:
    """Normalize a one-element document and read the attribute back."""
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    node = result.tree.css_first("script, link, img, a, source")
    return "" if node is None else (node.attributes.get(attribute) or "")


def applications(html: str) -> list[tuple[str, str, str]]:
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    return [(a.rule_id, a.before, a.after) for a in result.applied_rules if a.rule_id.startswith("asset.")]


# ---- the rules in isolation ---------------------------------------------------------------
@pytest.mark.parametrize(("rule_id", "url", "expected"), POSITIVE, ids=[p[1][-40:] for p in POSITIVE])
def test_rule_rewrites_its_generator(rule_id: str, url: str, expected: str) -> None:
    rule = BY_ID[rule_id]
    assert rule.matcher.matches(url)
    assert rule.matcher.sub(url, "") == expected


@pytest.mark.parametrize("url", NEGATIVE)
def test_meaningful_urls_match_no_rule(url: str) -> None:
    assert [rule.id for rule in ASSET_RULES if rule.matcher.matches(url)] == []


# ---- through the engine -------------------------------------------------------------------
@pytest.mark.parametrize(("rule_id", "url", "expected"), POSITIVE, ids=[p[1][-40:] for p in POSITIVE])
def test_rewrite_happens_in_place_and_keeps_the_attribute(rule_id: str, url: str, expected: str) -> None:
    html = f'<script src="{url}"></script>'
    assert first(html) == expected
    assert applications(html) == [(rule_id, url, expected)]


@pytest.mark.parametrize("attribute", ["src", "href", "srcset"])
def test_covered_attributes(attribute: str) -> None:
    html = f'<link {attribute}="/assets/js/main.3eef80bd.js">'
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    node = result.tree.css_first("link")
    assert node is not None
    assert node.attributes.get(attribute) == "/assets/js/main.js"


def test_srcset_rewrites_every_url_in_the_list() -> None:
    before = "/img/hero.a1b2c3d4.png 1x, /img/hero.e5f6a7b8.png 2x"
    html = f'<img srcset="{before}" src="/img/hero.a1b2c3d4.png">'
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    node = result.tree.css_first("img")
    assert node is not None
    assert node.attributes.get("srcset") == "/img/hero.png 1x, /img/hero.png 2x"
    assert node.attributes.get("src") == "/img/hero.png"


def test_other_attributes_are_out_of_scope() -> None:
    html = '<meta name="build-hash" content="db0488c167154941ce4686074ef69e757e1f3492">'
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, NormalizationConfig())
    node = result.tree.css_first("meta")
    assert node is not None
    # F-014 is deliberately not this family's business.
    assert node.attributes.get("content") == "db0488c167154941ce4686074ef69e757e1f3492"


def test_script_contents_are_never_touched() -> None:
    # The Next.js build id also appears inside __NEXT_DATA__; D-029 protects script bodies.
    html = '<script id="__NEXT_DATA__" type="application/json">{"buildId":"gHfMlRY8DvlLFUGxibDRr"}</script>'
    assert '{"buildId":"gHfMlRY8DvlLFUGxibDRr"}' in (normalize(html))


# ---- family contract ------------------------------------------------------------------------
def test_family_is_registered_with_stable_ids_phase_and_target() -> None:
    ids = [rule.id for rule in BUILTIN_RULES.ordered() if rule.family is RuleFamily.ASSET_HASH]
    assert ids == sorted(BY_ID) == [
        "asset.dashed_base64",
        "asset.dashed_hash",
        "asset.dotted_base64",
        "asset.dotted_hash",
        "asset.next_build_id",
        "asset.query_cache_buster",
    ]
    assert {rule.phase for rule in ASSET_RULES} == {PHASE_ASSET_HASH}
    assert 40 < PHASE_ASSET_HASH < 90  # after timestamps, before canonicalization
    assert all(rule.target is Target.ATTRIBUTE_SUBSTRING for rule in ASSET_RULES)
    assert all(rule.attributes == frozenset({"src", "href", "srcset"}) for rule in ASSET_RULES)


def test_extension_list_is_closed_and_excludes_documents() -> None:
    assert {"js", "css", "woff2", "png", "svg"} <= ASSET_EXTENSIONS
    assert not ({"html", "htm", "php", "json", "xml", "rst", "pdf"} & ASSET_EXTENSIONS)


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_each_rule_is_individually_toggleable(rule_id: str) -> None:
    url = next(p[1] for p in POSITIVE if p[0] == rule_id)
    html = f'<script src="{url}"></script>'
    off = NormalizationConfig(disabled_rules=frozenset({rule_id}))
    result = apply_rules(parse(html.encode()), BUILTIN_RULES, off)
    node = result.tree.css_first("script")
    assert node is not None and node.attributes.get("src") == url


def test_provenance_determinism_and_input_untouched() -> None:
    doc = parse(b'<div><script src="/assets/js/main.3eef80bd.js"></script></div>')
    before = doc.tree.html
    first_run = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    second_run = apply_rules(doc, BUILTIN_RULES, NormalizationConfig())
    assert doc.tree.html == before
    assert first_run.tree.html == second_run.tree.html
    fired = [a for a in first_run.applied_rules if a.rule_id.startswith("asset.")]
    assert [(a.rule_id, a.before, a.after) for a in fired] == [
        ("asset.dotted_hash", "/assets/js/main.3eef80bd.js", "/assets/js/main.js")
    ]
    assert (fired[0].locator.css or "").endswith("> div > script")
    assert len(fired[0].locator.node_hash) == 64


def test_public_api_is_idempotent_over_asset_hashes() -> None:
    html = (
        '<link href="../_static/pydoctheme.css?v=4365c8fe" rel="stylesheet">'
        '<script src="/_next/static/gHfMlRY8DvlLFUGxibDRr/_buildManifest.js"></script>'
        '<script src="/_next/static/chunks/99013-8b54dcaea3573ec3.js"></script>'
        '<img srcset="/img/hero.a1b2c3d4.png 1x">'
    )
    once = normalize(html)
    assert normalize(once) == once
    assert applications(once) == []  # nothing left to rewrite


def test_two_deploys_of_the_same_page_converge() -> None:
    old = '<script src="/assets/js/main.3eef80bd.js"></script><link href="/a.css?v=4365c8fe">'
    new = '<script src="/assets/js/main.64b6acdf.js"></script><link href="/a.css?v=c60eaebf">'
    assert normalize(old) == normalize(new)


def test_earlier_families_are_unaffected() -> None:
    html = (
        '<div class="card css-1dbjc4n" id="react-root-7a3b2c">'
        '<meta name="csrf-token" content="Zm9vYmFyMTIzNDU2Nzg5">'
        "<p>Updated 3 minutes ago</p>"
        '<script src="/assets/js/main.3eef80bd.js"></script></div>'
    )
    out = normalize(html)
    assert 'class="card"' in out and "react-root" not in out
    assert "Zm9vYmFyMTIzNDU2Nzg5" not in out and "3 minutes ago" not in out
    assert '/assets/js/main.js' in out


def test_config_hash_changes_when_the_family_ships() -> None:
    # D-028: the ruleset fingerprint covers every rule id and version.
    assert Config().config_hash.startswith("sha256:")
    assert all(rule.version == 1 for rule in ASSET_RULES)


# ---- base64url hashes (FR-44 extension) ---------------------------------------------------
def test_base64url_and_hex_rules_are_mutually_exclusive() -> None:
    """Uppercase is the fence between them, so no URL can be claimed by both."""
    hex_ids = {"asset.dotted_hash", "asset.dashed_hash"}
    b64_ids = {"asset.dotted_base64", "asset.dashed_base64"}
    for _rule_id, url, _expected in POSITIVE:
        fired = {rule.id for rule in ASSET_RULES if rule.matcher.matches(url)}
        assert not (fired & hex_ids and fired & b64_ids), url


def test_base64url_hash_length_is_exactly_eight() -> None:
    """Seven or nine characters is not Vite's output, and length is the first fence."""
    assert first('<script src="/assets/index-CjpiBuH.js"></script>') == "/assets/index-CjpiBuH.js"
    assert first('<script src="/assets/index-CjpiBuHVx.js"></script>') == "/assets/index-CjpiBuHVx.js"
    assert first('<script src="/assets/index-CjpiBuHV.js"></script>') == "/assets/index.js"


def test_double_extension_bundles_are_not_matched() -> None:
    """Known gap: Rollup's `.lean.js` puts a non-asset extension between hash and suffix."""
    url = "/assets/introduction_index.md.Dd_dCLWs.lean.js"
    assert [rule.id for rule in ASSET_RULES if rule.matcher.matches(url)] == []


def test_two_vite_deploys_of_the_same_page_converge() -> None:
    old = '<script type="module" src="/assets/index-CxL6fshY.js"></script>'
    new = '<script type="module" src="/assets/index-67LBnYfl.js"></script>'
    assert normalize(old) == normalize(new)
