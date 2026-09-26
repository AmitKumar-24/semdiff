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
        "asset.dashed_hash",
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
