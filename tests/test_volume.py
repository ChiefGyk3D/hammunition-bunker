# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from bunker import volume
from bunker.volume import Locked, RunLock, UnsafeName


def test_the_engine_library_imports_in_a_fresh_interpreter() -> None:
    """The engine's hammunition.fetch cannot be the package's first import
    (fetch -> backends -> apt_repo -> fetch); bunker.enginelib orders it."""
    done = subprocess.run(
        [sys.executable, "-c", "import bunker.enginelib"], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize(
    ("unit", "name"),
    [
        ("osm-regions", "../../etc"),
        ("osm-regions", "north-america/../../x"),
        ("osm-regions", ".hidden"),
        ("osm-regions", "a/.incoming"),
        ("osm-regions", "a//b"),
        ("osm-regions", ""),
        ("osm-regions", "/etc/passwd"),
        ("osm-regions", "a/b\x00"),
        ("osm-regions", "a\\b"),
        ("osm/regions", "x"),
        (".incoming", "x"),
        ("..", "x"),
        ("index.json", "x"),
        ("status.html", "x"),
        ("Upper", "x"),
        ("", "x"),
    ],
)
def test_unsafe_names_are_refused(tmp_path: Path, unit: str, name: str) -> None:
    with pytest.raises(UnsafeName):
        volume.artifact_dir(tmp_path, unit, name)


def test_layout(tmp_path: Path) -> None:
    assert (
        volume.artifact_dir(tmp_path, "osm-regions", "north-america/us/vermont")
        == tmp_path / "osm-regions" / "north-america" / "us" / "vermont"
    )
    assert volume.artifact_dir(tmp_path, "country-files", "cty.dat") == (
        tmp_path / "country-files" / "cty.dat"
    )
    assert volume.file_name("https://p/x/vermont-260101.osm.pbf?a=b") == "vermont-260101.osm.pbf"


def test_hash_file(tmp_path: Path) -> None:
    path = tmp_path / "f"
    data = b"x" * 200_000
    path.write_bytes(data)
    assert volume.hash_file(path) == (
        hashlib.sha256(data).hexdigest(),
        hashlib.md5(data, usedforsecurity=False).hexdigest(),
    )


def test_sidecar_round_trip_and_format(tmp_path: Path) -> None:
    path = tmp_path / "vermont.osm.pbf"
    sha = "c" * 64
    volume.write_sidecar(path, sha)
    assert (tmp_path / "vermont.osm.pbf.sha256").read_text() == f"{sha}  vermont.osm.pbf\n"
    assert volume.read_sidecar(path) == sha


def test_a_bad_sidecar_reads_as_none(tmp_path: Path) -> None:
    path = tmp_path / "f"
    assert volume.read_sidecar(path) is None
    (tmp_path / "f.sha256").write_text("not a digest\n")
    assert volume.read_sidecar(path) is None


class Commits:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None, bool]] = []
        self.old: Path | None = None

    def __call__(self, path: str, previous: str | None) -> None:
        still_there = self.old is not None and self.old.exists()
        self.seen.append((path, previous, still_there))


def incoming(tmp_path: Path, data: bytes) -> tuple[Path, str]:
    folder = tmp_path / ".incoming"
    folder.mkdir(exist_ok=True)
    path = folder / hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


def test_first_install(tmp_path: Path) -> None:
    src, sha = incoming(tmp_path, b"one")
    commits = Commits()
    path, prev = volume.install(
        tmp_path, "u", "a/b", src, "b-1.dat", sha, keep_previous=True, current=None, commit=commits
    )
    assert (path, prev) == ("u/a/b/b-1.dat", None)
    assert (tmp_path / path).read_bytes() == b"one"
    assert volume.read_sidecar(tmp_path / path) == sha
    assert not src.exists()
    assert commits.seen == [("u/a/b/b-1.dat", None, False)]


def test_a_new_name_keeps_the_old_as_previous(tmp_path: Path) -> None:
    src, sha = incoming(tmp_path, b"one")
    first, _ = volume.install(
        tmp_path, "u", "a", src, "a-1.dat", sha, keep_previous=True, current=None, commit=Commits()
    )
    src, sha2 = incoming(tmp_path, b"two")
    commits = Commits()
    commits.old = tmp_path / first
    path, prev = volume.install(
        tmp_path, "u", "a", src, "a-2.dat", sha2, keep_previous=True, current=first, commit=commits
    )
    assert path == "u/a/a-2.dat"
    assert prev == "u/a/a-1.dat.previous"
    assert (tmp_path / prev).read_bytes() == b"one"
    assert volume.read_sidecar(tmp_path / prev) == sha
    assert not (tmp_path / first).exists()
    # The index learned the new path while the old copy was still being served.
    assert commits.seen == [(path, prev, True)]


def test_the_same_name_keeps_a_linked_previous(tmp_path: Path) -> None:
    src, sha = incoming(tmp_path, b"one")
    first, _ = volume.install(
        tmp_path,
        "u",
        "a",
        src,
        "latest.dat",
        sha,
        keep_previous=True,
        current=None,
        commit=Commits(),
    )
    src, sha2 = incoming(tmp_path, b"two")
    path, prev = volume.install(
        tmp_path,
        "u",
        "a",
        src,
        "latest.dat",
        sha2,
        keep_previous=True,
        current=first,
        commit=Commits(),
    )
    assert path == first
    assert prev == "u/a/latest.dat.previous"
    assert (tmp_path / path).read_bytes() == b"two"
    assert (tmp_path / prev).read_bytes() == b"one"
    assert volume.read_sidecar(tmp_path / path) == sha2
    assert volume.read_sidecar(tmp_path / prev) == sha


def test_only_one_previous_is_kept(tmp_path: Path) -> None:
    current = None
    for n in range(1, 4):
        src, sha = incoming(tmp_path, f"v{n}".encode())
        current, _ = volume.install(
            tmp_path,
            "u",
            "a",
            src,
            f"a-{n}.dat",
            sha,
            keep_previous=True,
            current=current,
            commit=Commits(),
        )
    names = sorted(p.name for p in (tmp_path / "u" / "a").iterdir())
    assert names == ["a-2.dat.previous", "a-2.dat.previous.sha256", "a-3.dat", "a-3.dat.sha256"]


def test_keep_previous_false_keeps_none(tmp_path: Path) -> None:
    current = None
    for n in range(1, 3):
        src, sha = incoming(tmp_path, f"v{n}".encode())
        current, prev = volume.install(
            tmp_path,
            "u",
            "a",
            src,
            f"a-{n}.dat",
            sha,
            keep_previous=False,
            current=current,
            commit=Commits(),
        )
        assert prev is None
    assert sorted(p.name for p in (tmp_path / "u" / "a").iterdir()) == ["a-2.dat", "a-2.dat.sha256"]


def test_a_current_outside_the_artifact_is_ignored(tmp_path: Path) -> None:
    """An index entry is data read from disk: a path it names outside the
    artifact's own directory is never moved or deleted."""
    victim = tmp_path / "other" / "keep.dat"
    victim.parent.mkdir()
    victim.write_bytes(b"keep")
    src, sha = incoming(tmp_path, b"one")
    _, prev = volume.install(
        tmp_path,
        "u",
        "a",
        src,
        "a.dat",
        sha,
        keep_previous=False,
        current="other/keep.dat",
        commit=Commits(),
    )
    assert prev is None
    assert victim.read_bytes() == b"keep"


def test_the_lock_is_exclusive(tmp_path: Path) -> None:
    held = RunLock(tmp_path)
    with held, pytest.raises(Locked, match="in progress"), RunLock(tmp_path):
        pass
    with RunLock(tmp_path):
        pass


def test_disk_used_counts_files(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_bytes(b"x" * 1000)
    (tmp_path / "g").write_bytes(b"y" * 24)
    assert volume.disk_used(tmp_path) == 1024
