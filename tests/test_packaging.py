# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The image, the compose file, the quadlet and the workflows, checked
statically -- nothing here builds an image -- and the engine fetch the
image build runs, exercised against the loopback publisher."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import tarfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

import bunker
from tests.conftest import Publisher

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
PIN = re.compile(r"^\s*-?\s*uses:\s*(\S+?)@([0-9a-f]{40}) # v\d+(\.\d+)*\s*$")


def fetch_engine() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fetch_engine", ROOT / "packaging" / "fetch_engine.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tarball(members: dict[str, bytes], top: str = "Hammunition-0.16.0") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(f"{top}/{name}" if top else name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_there_are_workflows() -> None:
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "security.yml", "release.yml", "live.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path: Path) -> None:
    for line in path.read_text().splitlines():
        if re.match(r"^\s*-?\s*uses:", line):
            assert PIN.match(line), f"{path.name}: not pinned to a SHA with a # vX comment: {line}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflows_are_read_only_by_default(path: Path) -> None:
    doc: dict[str, Any] = yaml.safe_load(path.read_text())
    assert doc["permissions"] == {"contents": "read"}


# python-fuzz.yml first shipped in GYST v1.10.0; the other callers are still at the
# release they were pinned to, so it is checked on its own.
FUZZ_PIN = "b4dec64ea0efba8b0604339e283adb25da6fd430"  # v1.10.0's commit


def test_gyst_pins_agree() -> None:
    pins = set()
    for path in WORKFLOWS:
        for name, sha in re.findall(
            r"git-your-ship-together/\.github/workflows/(\S+)@([0-9a-f]{40})", path.read_text()
        ):
            if name == "python-fuzz.yml":
                assert sha == FUZZ_PIN, f"{path.name}: python-fuzz.yml is not at v1.10.0's commit"
            else:
                pins.add(sha)
    assert len(pins) == 1, f"the GYST workflows are pinned to more than one commit: {pins}"


def test_ci_is_gysts_python_ci() -> None:
    doc: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert "python-ci.yml@" in doc["jobs"]["ci"]["uses"]  # `ci / CI green` is the gate


def test_checkout_never_persists_credentials() -> None:
    for path in WORKFLOWS:
        doc: dict[str, Any] = yaml.safe_load(path.read_text())
        for job in doc["jobs"].values():
            for step in job.get("steps", []):
                if "actions/checkout" in step.get("uses", ""):
                    assert step["with"]["persist-credentials"] is False, path.name


def test_dockerfile_posture() -> None:
    text = (ROOT / "Dockerfile").read_text()
    assert re.search(r"^FROM debian:trixie-slim", text, re.M)
    users = re.findall(r"^USER (\S+)", text, re.M)
    assert users and users[-1] not in ("root", "0")
    assert "curl" not in text and "wget" not in text
    assert not re.search(r"\|\s*(ba)?sh", text)
    assert "pip install --no-index" in text  # nothing from an index, pinned or not
    assert re.search(r'ENTRYPOINT \["bunker"\]', text)


def test_compose_and_quadlet_agree() -> None:
    compose: dict[str, Any] = yaml.safe_load((ROOT / "compose.yaml").read_text())
    service = compose["services"]["bunker"]
    quadlet = (ROOT / "packaging" / "bunker.container").read_text()
    image = f"ghcr.io/chiefgyk3d/hammunition-bunker:{bunker.__version__}"
    assert service["image"] == image
    assert f"Image={image}" in quadlet
    mounts = [v.split(":")[1] for v in service["volumes"]]
    assert mounts == ["/data", "/etc/bunker/bunker.toml"]
    assert service["volumes"][1].endswith(":ro")
    assert re.search(r"^Volume=\S+:/data(:\S+)?$", quadlet, re.M)
    assert re.search(r"^Volume=\S+:/etc/bunker/bunker.toml:ro", quadlet, re.M)
    assert service["restart"] == "unless-stopped"
    assert "index.json" in " ".join(service["healthcheck"]["test"])
    # Never 0.0.0.0 on the host side: the port is published on the LAN address.
    assert not any(str(p).startswith(("0.0.0.0", "8080")) for p in service["ports"])


def test_fetch_engine_extracts_a_verified_archive(publisher: Publisher, tmp_path: Path) -> None:
    data = tarball({"pyproject.toml": b"[project]\n", "catalog/packages/x.yaml": b"name: x\n"})
    url = publisher.put("/archive/v0.16.0.tar.gz", data)
    dest = tmp_path / "opt" / "hammunition"
    fetch_engine().main([url, hashlib.sha256(data).hexdigest(), str(dest)])
    assert (dest / "catalog" / "packages" / "x.yaml").read_bytes() == b"name: x\n"


def test_fetch_engine_refuses_a_wrong_hash(publisher: Publisher, tmp_path: Path) -> None:
    url = publisher.put("/archive/v0.16.0.tar.gz", tarball({"a": b"a"}))
    dest = tmp_path / "hammunition"
    with pytest.raises(SystemExit, match="does not match"):
        fetch_engine().main([url, "0" * 64, str(dest)])
    assert not dest.exists()


@pytest.mark.parametrize("digest", ["UNSET", "", "abc", "A" * 64])
def test_fetch_engine_refuses_the_placeholder(tmp_path: Path, digest: str) -> None:
    with pytest.raises(SystemExit, match="ENGINE_SHA256"):
        fetch_engine().main(["http://127.0.0.1:9/x.tar.gz", digest, str(tmp_path / "h")])


def test_fetch_engine_refuses_a_member_that_escapes(publisher: Publisher, tmp_path: Path) -> None:
    data = tarball({"../../evil": b"x"})
    url = publisher.put("/archive/evil.tar.gz", data)
    with pytest.raises(SystemExit):
        fetch_engine().main([url, hashlib.sha256(data).hexdigest(), str(tmp_path / "h")])
    assert not (tmp_path / "evil").exists()


def test_fetch_engine_refuses_file_urls(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="https"):
        fetch_engine().main(["file:///etc/passwd", "a" * 64, str(tmp_path / "h")])


def _without_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make extractall behave as on Python 3.11.2 (Debian 12): no ``filter`` keyword."""
    monkeypatch.delattr(tarfile, "data_filter", raising=False)

    def extractall(self: tarfile.TarFile, *args: object, **kwargs: object) -> None:
        raise AssertionError("the by-hand path must not call extractall")

    monkeypatch.setattr(tarfile.TarFile, "extractall", extractall)


def test_fetch_engine_extracts_without_filters(
    publisher: Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_filters(monkeypatch)
    data = tarball({"catalog/packages/x.yaml": b"name: x\n"})
    url = publisher.put("/archive/v0.16.0.tar.gz", data)
    dest = tmp_path / "opt" / "hammunition"
    fetch_engine().main([url, hashlib.sha256(data).hexdigest(), str(dest)])
    assert (dest / "catalog" / "packages" / "x.yaml").read_bytes() == b"name: x\n"


def test_fetch_engine_refuses_an_escape_without_filters(
    publisher: Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_filters(monkeypatch)
    data = tarball({"../../evil": b"x"})
    url = publisher.put("/archive/evil.tar.gz", data)
    with pytest.raises(SystemExit):
        fetch_engine().main([url, hashlib.sha256(data).hexdigest(), str(tmp_path / "h")])
    assert not (tmp_path / "evil").exists()


def test_fetch_engine_refuses_a_symlink_that_points_outside_without_filters(
    publisher: Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_filters(monkeypatch)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        link = tarfile.TarInfo("Hammunition-0.16.0/lnk")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../.."
        tar.addfile(link)
        info = tarfile.TarInfo("Hammunition-0.16.0/lnk/evil")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    data = buffer.getvalue()
    url = publisher.put("/archive/evil.tar.gz", data)
    with pytest.raises(SystemExit):
        fetch_engine().main([url, hashlib.sha256(data).hexdigest(), str(tmp_path / "h")])
    assert not (tmp_path / "evil").exists()


def test_fetch_engine_refuses_dotdot_inside_a_path_without_filters(
    publisher: Publisher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _without_filters(monkeypatch)
    data = tarball({"top/../../evil": b"x"})
    url = publisher.put("/archive/evil.tar.gz", data)
    with pytest.raises(SystemExit):
        fetch_engine().main([url, hashlib.sha256(data).hexdigest(), str(tmp_path / "h")])
    assert not (tmp_path / "evil").exists()
