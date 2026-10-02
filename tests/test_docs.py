# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The documentation is part of the deliverable, so it is tested: links and
repository paths resolve, the reference names every key, command and
document the code has, and the README ends as Hammunition's does."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bunker import checks, cli, config, engine

ROOT = Path(__file__).resolve().parent.parent
HAMMUNITION_README = ROOT.parent / "Hammunition" / "README.md"
TAIL = ROOT / "tests" / "data" / "support-tail.md"
DOCS = sorted(
    [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md", ROOT / "CLAUDE.md"]
    + [p for p in (ROOT / "docs").rglob("*.md") if "superpowers" not in p.parts]
)
REPO_DIRS = ("src/", "tests/", "docs/", "packaging/", ".github/", "media/")
HEADING = "## 💝 Support This Project"


def test_there_are_docs() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in DOCS}
    assert {"README.md", "docs/guide.md", "docs/reference.md"} <= names


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_links_resolve(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    targets = re.findall(r"\]\(([^)\s]+)\)", text) + re.findall(r'src="([^"]+)"', text)
    for target in targets:
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            continue
        file = target.split("#", 1)[0]
        assert (path.parent / file).exists(), f"{path.name}: {target} does not exist"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_backticked_repo_paths_exist(path: Path) -> None:
    """This project's prose cites files by backtick, so a markdown-only link
    check would validate almost nothing (the parent project's lesson)."""
    for token in re.findall(r"`([^`\s]+)`", path.read_text(encoding="utf-8")):
        if token.startswith(REPO_DIRS) and "<" not in token and "*" not in token:
            assert (ROOT / token.rstrip("/")).exists(), f"{path.name}: `{token}` does not exist"


def test_readme_ends_with_hammunitions_support_and_socials() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert HEADING in readme
    assert readme[readme.index(HEADING) :] == TAIL.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not HAMMUNITION_README.exists(), reason="no Hammunition checkout beside this one"
)
def test_the_tail_is_still_hammunitions() -> None:
    source = HAMMUNITION_README.read_text(encoding="utf-8")
    assert source[source.index(HEADING) :] == TAIL.read_text(encoding="utf-8")


def reference() -> str:
    return (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("key", [f"{t}.{k}" for t, keys in config._KNOWN.items() for k in keys])
def test_every_config_key_is_documented(key: str) -> None:
    assert f"`{key}`" in reference()


@pytest.mark.parametrize("command", sorted(cli.COMMANDS))
def test_every_command_is_documented(command: str) -> None:
    assert f"`bunker {command}" in reference()


def test_engine_argv_matches_reference(tmp_path: Path) -> None:
    path = tmp_path / "bunker.toml"
    path.write_text(
        f'[engine]\ncatalog = "{tmp_path}"\n'
        '[selection]\nmap_regions = ["region-one"]\nmap_freshness = "monthly"\n'
        'reference_books = ["book-one"]\nunits = ["unit-one"]\n',
        encoding="utf-8",
    )
    placeholders = {
        "--catalog": ("DIR", True),
        "--map-freshness": ("F", False),
        "--map-regions": ("R,...", True),
        "--reference-books": ("ID,...", True),
        "--units": ("U,...", True),
    }
    actual = engine.argv(config.load(path))
    documented_argv: list[str] = []
    index = 0
    while index < len(actual):
        token = actual[index]
        if token in placeholders:
            placeholder, optional = placeholders[token]
            item = f"{token} {placeholder}"
            documented_argv.append(f"[{item}]" if optional else item)
            index += 2
        else:
            documented_argv.append(token)
            index += 1

    section = reference().split("## What the Bunker asks the engine", 1)[1]
    command = re.search(r"```\n(.*?)\n```", section, re.DOTALL)
    assert command is not None
    assert command.group(1) == " ".join(documented_argv)


@pytest.mark.parametrize("kind", sorted(p.stem for p in (ROOT / "tests" / "golden").glob("*.json")))
def test_every_document_is_documented(kind: str) -> None:
    assert f"`{kind}`" in reference()


def test_the_example_config_is_the_reference_config() -> None:
    """Every key the example sets is one the reference documents."""
    example = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    table = ""
    for line in example.splitlines():
        header = re.match(r"^\[([a-z.]+)\]", line)
        if header:
            table = header.group(1)
            continue
        key = re.match(r"^([a-z_]+) =", line)
        if key and "." not in table:
            assert f"`{table}.{key.group(1)}`" in reference()


@pytest.mark.parametrize("kind", sorted(checks.KINDS))
@pytest.mark.parametrize("page", ["README.md", "docs/reference.md"])
def test_every_check_kind_is_in_the_kinds_table(kind: str, page: str) -> None:
    """The table in the code (`bunker.checks.KINDS`) and the two tables a reader
    sees must list the same kinds: a kind added to one and not the others is the
    drift this catches."""
    text = (ROOT / page).read_text(encoding="utf-8")
    assert re.search(rf"^\| `{re.escape(kind)}` \|", text, re.MULTILINE), (
        f"{page} has no row for the check kind `{kind}`"
    )


@pytest.mark.parametrize("page", ["README.md", "docs/reference.md", "docs/guide.md"])
def test_the_ruling_and_the_switch_are_stated(page: str) -> None:
    text = (ROOT / page).read_text(encoding="utf-8")
    assert "2026-10-02" in text and "hold_unverified" in text
    assert "client.csv" in text
