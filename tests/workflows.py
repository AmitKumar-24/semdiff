"""A YAML reader for the two workflow files, and nothing else (D-051).

D-051's release gates live in `.github/workflows/release.yml`, where until now nothing could
assert them: a workflow is data, and nothing this repository depends on can read it. `pyyaml`
is the obvious answer and was rejected -- a dependency added so that a handful of tests can
read two files this repository wrote itself, when NFR-2's principle is that a package is
declared by the code that needs it. This reads the subset those two files use and *refuses*
everything else: a workflow that later reaches for a folded scalar, an anchor, a non-empty flow
mapping or a tab raises `YamlSubsetError` rather than being quietly misread. Loud failure is
the point -- a silently wrong reading of `permissions:` would be worse than having no test.

Supported: block mappings, `- ` sequences (of scalars or of mappings), `|` literal block
scalars, flow sequences, the empty flow mapping, single- and double-quoted scalars without
escapes, plain scalars, `true`/`false`/`null`, and both full-line and trailing comments. `on:`
comes back as the string key ``"on"``, where PyYAML would hand back ``True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

#: Scalars YAML spells as something other than a string.
CONSTANTS: dict[str, Any] = {"true": True, "false": False, "null": None, "~": None}
#: A value starting with one of these has left the supported subset.
REJECTED = (">", "&", "*", "!", "|-", "|+")


class YamlSubsetError(Exception):
    """The file uses YAML this reader does not support, so it refuses to guess."""


def load(path: Path) -> dict[str, Any]:
    """Parse one workflow file into plain dicts, lists and scalars."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if "\t" in text:
        raise YamlSubsetError(f"{path.name}: tabs are not YAML indentation")
    reader = _Reader(path.name, text.split("\n"))
    document = reader.block(0)
    reader.expect_exhausted()
    if not isinstance(document, dict):
        raise YamlSubsetError(f"{path.name}: the document is not a mapping")
    return document


def _strip_comment(raw: str) -> str:
    """Drop a trailing `# ...`, but only one that is outside quotes."""
    quote = ""
    for position, character in enumerate(raw):
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character == "#" and (position == 0 or raw[position - 1] in " \t"):
            return raw[:position]
    return raw


def _split_flow(body: str, fail: Any) -> list[str]:
    """Top-level commas of a flow sequence, ignoring any inside quotes."""
    parts: list[str] = []
    quote = ""
    current = ""
    for character in body:
        if quote:
            current += character
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
            current += character
        elif character == ",":
            parts.append(current)
            current = ""
        else:
            current += character
    if quote:
        raise fail(f"unterminated quote in a flow sequence: {body!r}")
    if current.strip() or parts:
        parts.append(current)
    return [part.strip() for part in parts]


class _Reader:
    def __init__(self, name: str, lines: list[str]) -> None:
        self.name = name
        self.lines = lines
        self.at = 0

    def _fail(self, message: str) -> YamlSubsetError:
        return YamlSubsetError(f"{self.name}:{self.at + 1}: {message}")

    def _significant(self) -> tuple[int, str] | None:
        """The next line that is neither blank nor a whole-line comment."""
        while self.at < len(self.lines):
            line = self.lines[self.at]
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                if stripped.startswith("---") or stripped.startswith("? "):
                    raise self._fail(f"unsupported YAML: {stripped!r}")
                return len(line) - len(line.lstrip(" ")), stripped
            self.at += 1
        return None

    def expect_exhausted(self) -> None:
        if self._significant() is not None:
            raise self._fail("content after the document")

    def block(self, indent: int) -> Any:
        head = self._significant()
        if head is None or head[0] != indent:
            raise self._fail(f"expected a block at indent {indent}")
        return self.sequence(indent) if head[1].startswith("- ") else self.mapping(indent)

    def mapping(self, indent: int, into: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {} if into is None else into
        while True:
            head = self._significant()
            if head is None:
                return result
            found, content = head
            if found < indent:
                return result
            if found > indent:
                raise self._fail(f"indent {found} where {indent} was expected")
            if content.startswith("-"):
                raise self._fail("a sequence item where a mapping key was expected")
            key, separator, rest = content.partition(":")
            if not separator:
                raise self._fail(f"not a mapping entry: {content!r}")
            if key.strip() in result:
                raise self._fail(f"duplicate key {key.strip()!r}")
            self.at += 1
            result[key.strip()] = self.value(rest.strip(), indent)

    def sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while True:
            head = self._significant()
            if head is None or head[0] < indent:
                return items
            found, content = head
            if found != indent or not content.startswith("- "):
                return items
            body = content[2:].strip()
            self.at += 1
            key, separator, rest = body.partition(":")
            if not separator:
                items.append(self.scalar(body))
                continue
            # A mapping that starts on the dash line and continues under the dash's content.
            item: dict[str, Any] = {key.strip(): self.value(rest.strip(), indent + 2)}
            items.append(self.mapping(indent + 2, item))

    def value(self, rest: str, indent: int) -> Any:
        if rest in REJECTED or rest[:1] in (">", "&", "*", "!"):
            raise self._fail(f"unsupported value: {rest!r}")
        if rest == "|":
            return self.literal(indent)
        if rest:
            return self.scalar(rest)
        nested = self._significant()
        if nested is None or nested[0] <= indent:
            return None
        return self.block(nested[0])

    def literal(self, indent: int) -> str:
        """A `|` block: every following line indented past the key, taken verbatim."""
        collected: list[str] = []
        margin: int | None = None
        while self.at < len(self.lines):
            line = self.lines[self.at]
            if not line.strip():
                collected.append("")
                self.at += 1
                continue
            found = len(line) - len(line.lstrip(" "))
            if found <= indent:
                break
            if margin is None:
                margin = found
            if found < margin:
                raise self._fail("a block scalar line is less indented than its first")
            collected.append(line[margin:])
            self.at += 1
        while collected and not collected[-1]:
            collected.pop()
        if not collected:
            raise self._fail("an empty block scalar")
        return "\n".join(collected) + "\n"

    def scalar(self, raw: str) -> Any:
        text = _strip_comment(raw).strip()
        if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
            inner = text[1:-1]
            if text[0] in inner or "\\" in inner:
                raise self._fail(f"quoting this reader does not handle: {text!r}")
            return inner
        if text.startswith("["):
            if not text.endswith("]"):
                raise self._fail(f"unterminated flow sequence: {text!r}")
            return [self.scalar(part) for part in _split_flow(text[1:-1], self._fail)]
        if text.startswith("{"):
            if text != "{}":
                raise self._fail(f"only the empty flow mapping is supported: {text!r}")
            return {}
        if text in CONSTANTS:
            return CONSTANTS[text]
        return text
