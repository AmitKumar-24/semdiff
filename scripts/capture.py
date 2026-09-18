"""Capture one page snapshot for the corpus (T-04, D-024). Not part of the library.

Usage: python scripts/capture.py <fixture-id> <url> <old|new> [--out DIR]

Writes DIR/<fixture-id>/<label>.html (response bytes, verbatim) and
DIR/<fixture-id>/<label>.meta.json (url, final_url, status, content_type, captured_at).
Refuses to fetch if robots.txt disallows the URL for this User-Agent.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

USER_AGENT = "SemDiff-corpus-capture/0.1 (research corpus capture; see repository NOTICE)"
TIMEOUT_SECONDS = 30
DEFAULT_OUT = Path(__file__).resolve().parents[1] / ".captures"


def robots_allows(url: str) -> bool:
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    # Fetch with our own User-Agent: RobotFileParser.read() would use Python's default
    # UA, which some hosts reject with 403, and a 403 is treated as "disallow all".
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code not in (401, 403)  # 404 etc.: nothing forbids the fetch
    except (urllib.error.URLError, OSError):
        return True
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def capture(fixture_id: str, url: str, label: str, out: Path) -> Path:
    if not robots_allows(url):
        sys.exit(f"robots.txt disallows {url} for {USER_AGENT!r}; nothing written")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        meta = {
            "url": url,
            "final_url": response.geturl(),
            "status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "captured_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
    target = out / fixture_id
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{label}.html").write_bytes(body)
    (target / f"{label}.meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_id")
    parser.add_argument("url")
    parser.add_argument("label", choices=["old", "new"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    target = capture(args.fixture_id, args.url, args.label, args.out)
    print(f"wrote {target / (args.label + '.html')}")


if __name__ == "__main__":
    main()
