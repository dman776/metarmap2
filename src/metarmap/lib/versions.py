"""
Release versions: a release is a git tag like v2.8.4 (or 2.8.4). Anything else, such as a pre-release (v2.9.0-rc1)
or a tag that isn't a version, isn't a release.
"""
import re
from typing import Iterable, List, Optional, Tuple

_RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse(text) -> Optional[Tuple[int, int, int]]:
    """(2, 8, 4) for "v2.8.4" or "2.8.4"; None if it isn't a release."""
    match = _RELEASE.match(str(text or "").strip())
    return tuple(int(n) for n in match.groups()) if match else None


def releases(tags: Iterable[str]) -> List[str]:
    """The release tags among `tags`, newest first (by version, not by date)."""
    return sorted((tag for tag in tags if parse(tag)), key=parse, reverse=True)


def is_newer(tag, current) -> bool:
    """Whether release `tag` is newer than version `current` (a version that can't be read counts as older)."""
    tag_version, current_version = parse(tag), parse(current)
    return tag_version is not None and (current_version is None or tag_version > current_version)


def same(tag, current) -> bool:
    return parse(tag) is not None and parse(tag) == parse(current)
