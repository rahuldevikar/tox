from __future__ import annotations

from typing import TYPE_CHECKING

from tox.util.path import ensure_cachedir_tag, ensure_empty_dir

if TYPE_CHECKING:
    from pathlib import Path


def test_ensure_empty_dir_file(tmp_path: Path) -> None:
    dest = tmp_path / "a"
    dest.write_text("")
    ensure_empty_dir(dest)
    assert dest.is_dir()
    assert not list(dest.iterdir())


def test_ensure_cachedir_tag_creates_file(tmp_path: Path) -> None:
    ensure_cachedir_tag(tmp_path)
    tag = tmp_path / "CACHEDIR.TAG"
    assert tag.is_file()
    content = tag.read_text(encoding="utf-8")
    assert content.startswith("Signature: 8a477f597d28d172789f06886806bc55")


def test_ensure_cachedir_tag_idempotent(tmp_path: Path) -> None:
    ensure_cachedir_tag(tmp_path)
    tag = tmp_path / "CACHEDIR.TAG"
    first_content = tag.read_text(encoding="utf-8")
    ensure_cachedir_tag(tmp_path)
    assert tag.read_text(encoding="utf-8") == first_content


def test_ensure_cachedir_tag_preserves_existing(tmp_path: Path) -> None:
    tag = tmp_path / "CACHEDIR.TAG"
    custom = "Signature: 8a477f597d28d172789f06886806bc55\n# custom content\n"
    tag.write_text(custom, encoding="utf-8")
    ensure_cachedir_tag(tmp_path)
    assert tag.read_text(encoding="utf-8") == custom
