from __future__ import annotations

from shutil import rmtree
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_CACHEDIR_TAG_HEADER = "Signature: 8a477f597d28d172789f06886806bc55"
_CACHEDIR_TAG_CONTENT = f"""\
{_CACHEDIR_TAG_HEADER}
# This file is a cache directory tag created by tox.
# For information about cache directory tags, see:
#	https://bford.info/cachedir/spec.html
"""


def ensure_empty_dir(path: Path, except_filename: str | None = None) -> None:
    if path.exists():
        if path.is_dir():
            for sub_path in path.iterdir():
                if sub_path.name == except_filename:
                    continue
                if sub_path.is_dir():
                    rmtree(sub_path, ignore_errors=True)
                else:
                    sub_path.unlink()
        else:
            path.unlink()
            path.mkdir()
    else:
        path.mkdir(parents=True)


def ensure_cachedir_tag(path: Path) -> None:
    """Place a ``CACHEDIR.TAG`` inside *path* if one is not already present.

    The tag follows the `Cache Directory Tagging Specification <https://bford.info/cachedir/spec.html>`_.

    """
    tag = path / "CACHEDIR.TAG"
    if not tag.exists():
        tag.write_text(_CACHEDIR_TAG_CONTENT, encoding="utf-8")


__all__ = [
    "ensure_cachedir_tag",
    "ensure_empty_dir",
]
