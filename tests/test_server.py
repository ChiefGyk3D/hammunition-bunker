# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later

"""The server, as a real HTTP server on loopback, over a volume a real run wrote."""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from bunker import server
from bunker.enginelib import Fetcher, MirrorPath, RemoteArtifact
from tests.scene import REGION, TILE, Scene, md5, sha


class Served:
    def __init__(self, root: Path) -> None:
        self.httpd = server.make_server(root, "127.0.0.1", 0, quiet=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def request(
        self, path: str, method: str = "GET", headers: dict[str, str] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()


@pytest.fixture
def served(scene: Scene) -> Iterator[Served]:
    scene.run()
    s = Served(scene.root)
    try:
        yield s
    finally:
        s.httpd.shutdown()
        s.httpd.server_close()


def test_the_mirror_path_serves_the_bytes(scene: Scene, served: Served) -> None:
    status, headers, body = served.request(f"/osm-regions/{REGION}")
    assert status == 200
    assert body == scene.data["region"]
    assert headers["Content-Length"] == str(len(body))
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_a_percent_quoted_mirror_path(scene: Scene, served: Served) -> None:
    """The engine quotes each segment (hammunition.fetch.mirror_url)."""
    status, _, body = served.request("/country%2Dfiles/cty%2Edat")
    assert status == 200 and body == scene.data["cty"]


def test_head_answers_with_the_size(scene: Scene, served: Served) -> None:
    status, headers, body = served.request(f"/dem-copernicus/{TILE}", "HEAD")
    assert status == 200
    assert headers["Content-Length"] == str(len(scene.data["tile"]))
    assert body == b""


def test_the_raw_path_and_its_sidecar(scene: Scene, served: Served) -> None:
    path = scene.entry("osm-regions", REGION).path
    assert path is not None
    assert served.request("/" + path)[2] == scene.data["region"]
    status, _, body = served.request("/" + path + ".sha256")
    assert status == 200
    assert body.decode().split()[0] == sha(scene.data["region"])


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [
        ("bytes=0-99", 0, 99),
        ("bytes=100-", 100, None),
        ("bytes=-50", -50, None),
        ("bytes=10-999999999", 10, None),
    ],
)
def test_byte_ranges(
    scene: Scene, served: Served, header: str, start: int, end: int | None
) -> None:
    data = scene.data["region"]
    status, headers, body = served.request(f"/osm-regions/{REGION}", headers={"Range": header})
    expected = data[start:] if end is None else data[start : end + 1]
    assert status == 206
    assert body == expected
    first = start if start >= 0 else len(data) + start
    assert headers["Content-Range"] == f"bytes {first}-{first + len(expected) - 1}/{len(data)}"
    assert headers["Content-Length"] == str(len(expected))


def test_an_unsatisfiable_range(scene: Scene, served: Served) -> None:
    size = len(scene.data["region"])
    status, headers, _ = served.request(
        f"/osm-regions/{REGION}", headers={"Range": f"bytes={size}-"}
    )
    assert status == 416
    assert headers["Content-Range"] == f"bytes */{size}"


def test_several_ranges_get_the_whole_file(scene: Scene, served: Served) -> None:
    status, _, body = served.request(f"/osm-regions/{REGION}", headers={"Range": "bytes=0-1,5-6"})
    assert status == 200 and body == scene.data["region"]


def test_index_and_status(served: Served) -> None:
    status, headers, body = served.request("/index.json")
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["kind"] == "bunker-index"
    for path in ("/", "/status.html"):
        status, headers, body = served.request(path)
        assert status == 200 and body.startswith(b"<!doctype html>")
        assert "default-src 'none'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    "path",
    [
        "/.incoming/",
        "/.lock",
        "/.runs.jsonl",
        "/%2elock",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/../../etc/passwd",
        "/osm-regions/",
        "/osm-regions",
        "/osm-regions/north-america",
        "/osm-regions/north-america/us/vermont/../../../index.json",
        "/nothing/here",
        "/stray.bin",
        "/osm-regions/north-america/us/vermont/vermont-260101.osm.pbf.previous",
    ],
)
def test_hidden_paths_are_404(scene: Scene, served: Served, path: str) -> None:
    (scene.root / "stray.bin").write_bytes(b"not in the index")
    assert served.request(path)[0] == 404


def test_previous_copies_are_not_served(scene: Scene, served: Served) -> None:
    folder = scene.root / "osm-regions" / REGION
    (folder / "vermont-251201.osm.pbf.previous").write_bytes(b"old")
    assert served.request(f"/osm-regions/{REGION}/vermont-251201.osm.pbf.previous")[0] == 404


def test_only_get_and_head(served: Served) -> None:
    for method in ("POST", "PUT", "DELETE"):
        status, headers, _ = served.request("/index.json", method)
        assert status == 405
        assert headers["Allow"] == "GET, HEAD"


def test_a_corrupted_entry_is_not_offered(scene: Scene, served: Served) -> None:
    raw = json.loads((scene.root / "index.json").read_text())
    for item in raw["artifacts"]:
        if item["name"] == REGION:
            item["status"] = "corrupted"
    (scene.root / "index.json").write_text(json.dumps(raw))
    assert served.request(f"/osm-regions/{REGION}")[0] == 404


def test_an_index_path_outside_the_volume_is_not_served(
    scene: Scene, served: Served, tmp_path: Path
) -> None:
    """The index is data on disk; a path in it that leaves the volume is refused."""
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    raw = json.loads((scene.root / "index.json").read_text())
    raw["artifacts"][0]["path"] = "../secret.txt"
    (scene.root / "index.json").write_text(json.dumps(raw))
    assert served.request("/country-files/cty.dat")[0] == 404
    assert served.request("/../secret.txt")[0] == 404


def test_a_new_index_is_picked_up_without_a_restart(scene: Scene, served: Served) -> None:
    assert served.request(f"/dem-copernicus/{TILE}")[0] == 200
    raw = json.loads((scene.root / "index.json").read_text())
    raw["artifacts"] = [a for a in raw["artifacts"] if a["unit"] != "dem-copernicus"]
    (scene.root / "index.json").write_text(json.dumps(raw))
    assert served.request(f"/dem-copernicus/{TILE}")[0] == 404


def test_no_index_serves_nothing_but_404(tmp_path: Path) -> None:
    s = Served(tmp_path)
    try:
        assert s.request("/index.json")[0] == 404
        assert s.request("/osm-regions/x")[0] == 404
    finally:
        s.httpd.shutdown()
        s.httpd.server_close()


def test_the_engines_fetcher_takes_a_file_from_the_bunker(
    scene: Scene, served: Served, tmp_path: Path
) -> None:
    """The mirror contract end to end, through the engine's own code: the
    publisher URL is a 404, so the bytes can only have come from here."""
    fetcher = Fetcher(cache_dir=tmp_path / "cache", mirror=served.base + "/")
    data = scene.data["cty"]
    result = fetcher.fetch(
        RemoteArtifact(url=scene.pub.base + "/gone/bigcty.zip", sha256=sha(data)),
        mirror=MirrorPath("country-files", "cty.dat"),
    )
    assert result.source == "mirror"
    assert result.path.read_bytes() == data
    region = scene.data["region"]
    result = fetcher.fetch_md5(
        scene.pub.base + "/gone/vermont.osm.pbf",
        md5(region),
        expected_size=len(region),
        mirror=MirrorPath("osm-regions", REGION),
    )
    assert result.source == "mirror"
