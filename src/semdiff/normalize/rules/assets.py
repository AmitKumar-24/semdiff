"""Asset-hash rule family (T-23, FR-44): build hashes inside ``src``/``href``/``srcset``.

Content-hashed bundle names change on every deploy and are the most common real-world
difference between two snapshots of an unchanged page (F-013). Each rule removes the hash
and its delimiter, so the resource stays identifiable: ``main.3eef80bd.js`` → ``main.js``.

The hash is only recognisable from its context. ``?v=4365c8fe`` on a stylesheet is a cache
buster; ``?v=4anAwXYqLG8`` on a YouTube watch URL is the video. Every rule therefore
requires the path to end in a known asset extension (or to sit under a framework-specific
prefix), and never touches a document, an API path or a query it does not recognise.
"""

from __future__ import annotations

from semdiff.normalize.model import Action, GroupMatcher, NormalizationRule, RuleFamily, Target

PHASE_ASSET_HASH = 50

# Closed list: static assets only. Documents (html, php, rst), data (json, xml) and
# downloads (pdf) are excluded — a hash-shaped run in one of those is not ours to judge.
ASSET_EXTENSIONS = frozenset(
    "js mjs cjs css woff woff2 ttf otf eot png jpg jpeg gif svg webp avif ico map".split()
)
_EXT = f"(?:{'|'.join(sorted(ASSET_EXTENSIONS))})"
# A build hash, not a version or a counter: hex, 8+ chars, with at least one digit and one
# hex letter. Keeps `main.12345678.js` and `main.abcdefgh.js` out.
_HEX = r"(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{8,32}"
_CACHE_BUSTER_KEYS = "v ver rev t cb _".split()


def _rule(rule_id: str, pattern: str) -> NormalizationRule:
    return NormalizationRule(
        id=rule_id,
        family=RuleFamily.ASSET_HASH,
        target=Target.ATTRIBUTE_SUBSTRING,
        matcher=GroupMatcher(pattern),
        action=Action.STRIP,
        phase=PHASE_ASSET_HASH,
        attributes=frozenset({"src", "href", "srcset"}),
    )


ASSET_RULES: tuple[NormalizationRule, ...] = (
    # webpack, Docusaurus, umi: <name>.<hash>.<ext>
    _rule("asset.dotted_hash", rf"(?P<hash>\.{_HEX})(?=\.{_EXT}(?![A-Za-z0-9]))"),
    # Next.js chunks: <name>-<hash>.<ext>
    _rule("asset.dashed_hash", rf"(?P<hash>-{_HEX})(?=\.{_EXT}(?![A-Za-z0-9]))"),
    # Next.js build id as its own path segment, e.g. /_next/static/<id>/_buildManifest.js
    _rule("asset.next_build_id", r"(?<=/_next/static/)(?P<hash>[A-Za-z0-9_-]{16,}/)"),
    # Sphinx-style cache buster, only as the sole query of an asset URL.
    _rule(
        "asset.query_cache_buster",
        rf"\.{_EXT}(?P<hash>\?(?:{'|'.join(_CACHE_BUSTER_KEYS)})=[A-Za-z0-9]{{6,}})(?=[\s,]|$)",
    ),
)
