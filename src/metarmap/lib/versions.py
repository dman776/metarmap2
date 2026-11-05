"""
Release versions: a release is a git tag of three or four numbers, with or without a v. Since 2026-11 they're dates,
vYY.MM.DD, with a fourth number for another release the same day (v26.11.04, then v26.11.04.1); the ones before
were v1.1.0 to v3.2.0, which sort below every date. Anything else, such as a pre-release (v26.11.04-rc1) or a tag
that isn't a version, isn't a release.

A map on 3.2.0 or older reads only three numbers, so it doesn't see a four-number release; the first release of a
day is always a plain date, which it does see, and once it's on one it sees the rest.
"""

import re
from typing import Iterable, List, Optional, Tuple

_RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?$")


def parse(text) -> Optional[Tuple[int, ...]]:
    """
    (26, 11, 4) for "v26.11.04" or "26.11.04", (26, 11, 4, 1) for "v26.11.04.1", (2, 8, 4) for "v2.8.4"; None if it
    isn't a release. A fourth number sorts after the plain date: (26, 11, 4) < (26, 11, 4, 1) < (26, 11, 5).
    """
    match = _RELEASE.match(str(text or "").strip())
    return tuple(int(n) for n in match.groups() if n is not None) if match else None


def releases(tags: Iterable[str]) -> List[str]:
    """The release tags among `tags`, newest first (by version, not by date)."""
    return sorted((tag for tag in tags if parse(tag)), key=parse, reverse=True)


def is_newer(tag, current) -> bool:
    """Whether release `tag` is newer than version `current` (a version that can't be read counts as older)."""
    tag_version, current_version = parse(tag), parse(current)
    return tag_version is not None and (current_version is None or tag_version > current_version)


def same(tag, current) -> bool:
    return parse(tag) is not None and parse(tag) == parse(current)
