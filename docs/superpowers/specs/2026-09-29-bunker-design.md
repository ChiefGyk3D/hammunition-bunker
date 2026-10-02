# Hammunition Bunker — design

Status: approved in conversation 2026-09-29 (role: verified LAN mirror;
deployment: container image). This document is the spec the implementation
plan argues from.

## What it is

A service that keeps a verified copy of Hammunition's offline data fresh on a
NAS and serves it on the LAN, so that a field machine's `hammunition install`
takes its map regions, elevation tiles, reference books and the rest from the
LAN instead of the internet, and the copy on the NAS is never trusted, only
fast.

It is a sibling of [Hammunition](https://github.com/ChiefGyk3D/Hammunition)
in the sense of the separable-components rule: its own repository, its own
release line, the engine reached only through the engine's public interfaces.
It carries no catalog, no pins and no verification code of its own. Every
artifact it holds is one the engine already knows how to fetch and verify.

## What it is not

- Not a workstation tool. It has no install verb and no desktop. It never
  unpacks, converts or executes anything it downloads.
- Not a second source of truth. The pins live in Hammunition's catalog. The
  Bunker learns them by asking an installed engine, at a pinned release.
- Not a public mirror. It serves on a LAN, without authentication, because
  every consumer verifies every byte against a hash it already holds. Serving
  beyond the LAN is out of scope and documented as such.
- Not an apt mirror. Packages come from the distribution; this holds data.
- Not a push service. It does not copy anything to the field machine; the
  engine pulls. Pushing is a later piece, if ever.

## Roles

| | Hammunition (the engine) | Hammunition Bunker |
|---|---|---|
| Runs | on a workstation, by hand | on a NAS, on a schedule |
| Owns | the catalog, the pins, the verifier | a volume, a schedule, an index |
| Talks | `hammunition artifacts --json` (new) | HTTP on the LAN, read-only |
| Trusts | the hash in the catalog | nothing; re-hashes what it holds |

## The engine side (Hammunition changes, one decision entry)

Two additions to Hammunition, shipped in a Hammunition release the Bunker
pins as its floor.

### 1. `hammunition artifacts --json`

A read-only command listing every remote artifact the engine would fetch for
a selection, without a station and without installing anything. It is the
Bunker's only source of what to mirror.

Selection flags mirror station config's data keys and are given explicitly:

```
hammunition artifacts --json \
    --map-regions north-america/us/vermont,north-america/us/new-hampshire \
    --map-freshness yearly \
    [--units osm-regions,dem-copernicus,country-boundaries,...]
```

`--units` defaults to every unit with a `data` install block plus the
region-derived fetches (Geofabrik extracts, Copernicus tiles for those
regions). A unit that needs a selection the flags do not give (map units with
no `--map-regions`) is listed as deferred with the reason, the way `plan`
defers it, never silently dropped.

The document (one `ArtifactsDocument`, rendered like every other D-059
document) carries, per artifact:

| field | meaning |
|---|---|
| `unit` | the manifest name (`osm-regions`, `dem-copernicus`, `kiwix-library`, ...) |
| `name` | the artifact's stable name within the unit (region path, tile name, book name) |
| `url` | the publisher URL the engine itself would fetch |
| `check` | `sha256` (pinned by Hammunition), `md5-publisher` (Geofabrik's published MD5, fetched at plan time), `etag-md5` (Copernicus object metadata), `sha1-publisher` (the SHA-1 and size in CoMaps' own index), `sha256-publisher` (a `.meta4`/`.sha256` the engine reads; no unit produces it today) or `unverified-zip` (the ACMA register: no digest exists). The Bunker's table of them is `src/bunker/checks.py`; see "Check kinds" below |
| `digest` | always a hex digest, or null until the publisher's checksum has been read (D-070 as built: the field is never a URL) |
| `checksum_url` | where the publisher's checksum comes from when `check` is not `sha256`: the `.md5` URL, or the object URL whose HEAD carries the ETag |
| `size` | bytes, when known before the fetch |
| `licence` | the licence line the plan prints |
| `deferred` | null, or the reason this artifact cannot be listed for this selection |

Freshness (`yearly`, `monthly`, `latest`) changes which URL and which check a
region gets, exactly as it does in the plan. Nothing in the document is the
operator's: no station values are read.

### 2. A mirror in station config

Station config gains one optional key:

```
hammunition station set --mirror http://bunker.lan:8080/
```

`--clear-mirror` removes it. As built (D-070): only data is mirrored (data
files, map regions, terrain tiles), never source tarballs, binaries or
wheels; a mirror that does not answer within 10 s is skipped for the rest of
the run; every data fetch logs its source; the plan's *Data mirror* section
appears only when a step would ask the mirror; and a mirror does not make an
install work offline, because the plan still asks the publishers.

When set, the engine's verified fetch tries `<mirror>/<unit>/<name>` first
and falls back to the publisher URL on any failure (unreachable, 404, wrong
size, wrong hash), verifying the same digest either way. The plan says, per
artifact, which source it will try first and that the hash is checked
regardless; `--dry-run` shows the same. `--no-mirror` on `install` ignores
the key for one run. The transaction log records which source each fetch
actually came from.

The mirror is plain HTTP by design: the content is public data and the
check is the hash, not the transport. The docs say so, and say that a
mirror URL is a LAN address, never something reachable from the internet.

Both changes are one Hammunition decision entry (`D-0xx — A data artifact may
be taken from a LAN mirror the operator names, verified the same either way,
and the engine can list what it would fetch without a station`), with a
CLAUDE.md table row, `docs/reference/cli.md`, the JSON reference regenerated,
and the station config docs.

## The Bunker

### Configuration

One file, `bunker.toml`, bind-mounted read-only:

```toml
[engine]
# The hammunition executable the Bunker asks. Inside the image this is the
# pinned release installed at build time; outside it, any path.
command = "hammunition"

[selection]
map_regions = ["north-america/us/vermont", "north-america/us/new-hampshire"]
map_freshness = "yearly"
units = []            # empty = everything `artifacts` lists for the selection

[storage]
root = "/data"        # the bind-mounted volume
keep_previous = true  # last known-good copy is kept until the next good swap

[schedule]
default = "weekly"    # never | daily | weekly | monthly
[schedule.units]
osm-regions = "daily"
dem-copernicus = "never"      # the pin changes only with a Hammunition release
kiwix-library = "monthly"

[serve]
bind = "0.0.0.0"      # the container's interface; the compose file maps it to the LAN
port = 8080
```

The example file in the repo names public example regions only. The
maintainer's real selection lives on the NAS, never in the repo.

### The run

Every run, whether from the schedule or `bunker run` by hand:

1. Ask the engine: `hammunition artifacts --json` with the selection. A
   non-zero exit or an unparseable document fails the run, loudly, with the
   engine's stderr in the report.
2. For each listed artifact due under its unit's schedule (or every artifact
   with `--all`): resolve the expected digest. For `sha256`, from the
   document. For the publisher checks, fetch the publisher's checksum the
   way the engine does, through the engine's own code (`hammunition.fetch`
   imported as a library at the pinned release), so there is one verifier.
3. If the copy on disk exists and its sidecar digest equals the expected
   digest, re-hash the file on disk (not trust the sidecar) on the unit's
   `verify` cadence (default: every run for files under 1 GB, monthly
   above). A file whose bytes no longer match its sidecar is reported as
   corrupted and re-fetched.
4. Otherwise download to `<root>/.incoming/<unit>/<name>.<digest12>` through
   the engine's verified fetch. On success, move it into place atomically,
   write the sidecar `<name>.sha256` (always sha256 of the bytes, whatever
   the publisher's check was, so the mirror's own consumers verify one
   way), and if `keep_previous`, rename the previous good copy to
   `<name>.previous` (one kept, older ones deleted). On failure the previous
   copy stays in place and the failure is in the report.
5. Rewrite `<root>/index.json` and `<root>/status.html`.

Concurrency: one run at a time, `flock` on `<root>/.lock`; a second start
exits 125 with a line saying a run is in progress. Downloads within a run:
two at a time by default, configurable, never more than four. Bandwidth cap
optional (`[storage] max_rate = "20M"`), passed to the engine's transport.

### Check kinds, as built (2026-10-02)

The Bunker keeps one table of the check kinds (`src/bunker/checks.py`); the
document parser, the run, `verify`, `status`, `doctor` and the docs test read
it, and `tests/test_kinds.py` fails when the installed engine can emit a kind
that is not in it.

| Check | Verified by | Engine method |
|---|---|---|
| `sha256`, `sha256-publisher` | the sha256 (pinned, or the publisher's) | `Fetcher.fetch` |
| `md5-publisher`, `etag-md5` | the MD5 and the exact listed size | `Fetcher.fetch_md5` |
| `sha1-publisher` | the SHA-1 and the exact listed size | `Fetcher.fetch_sha1` |
| `unverified-zip` | no digest: the engine's structure check (zip CRC-32s, the tables its reader needs) | `Fetcher.fetch_checked` |

- **An unknown kind is refused by name**, with the engine's version (the
  document's `engine` field): not downloaded, listed under the run's
  `refused`, exit 1. The rest of the listing is still mirrored. An engine newer
  than `ENGINE_CONTRACT` (the newest release whose document the table was
  written against) adds a note to the run's `warnings` and to `doctor`; that is
  not a failure. `ENGINE_CONTRACT` is not the image's pin (`ENGINE_FLOOR`).
- **Methods the pinned engine lacks.** `sha1-publisher` and `unverified-zip`
  need `Fetcher.fetch_sha1`, `Fetcher.fetch_checked` and `hammunition.acma`,
  which the floor release (v0.16.0) does not have. The artifact fails by name
  saying which is missing; nothing is downloaded. The Bunker still starts on the
  floor because `hammunition.acma` is imported when needed.
- **Unverified artifacts, held by the maintainer's ruling (2026-10-02).** The
  ACMA register contains `client.csv` (licensees' names and addresses, which
  its licence bars passing on in a derivative); the ruling is that a Bunker may
  hold it anyway, "for users to download things and have their repository set
  up", and the engine never opens `client.csv`. The Bunker stores the file,
  records its size and fetch date, fetches it again when its unit's schedule is
  due, never marks it `stale` (no digest to compare), runs the engine's
  structure check on every fetch and on `bunker verify` (a damaged copy is
  discarded, the last good one keeps serving), and lists it under *Unverified,
  held by the maintainer's ruling* in `status`, the status page and `doctor`.
- **`[selection] hold_unverified`** (default `true`): `false` declines every
  such artifact by name, never fetches it, and withdraws one already held from
  the index (files left for the operator to delete). `doctor` names what is held
  and the switch's setting.

### The index

`index.json` is the Bunker's document, versioned, one per volume:

```json
{
  "kind": "bunker-index",
  "version": 1,
  "generated": "2026-09-29T23:00:00Z",
  "engine": {"version": "0.15.0"},
  "artifacts": [
    {
      "unit": "osm-regions",
      "name": "north-america/us/vermont",
      "path": "osm-regions/north-america/us/vermont-latest.osm.pbf",
      "sha256": "…",
      "size": 123456789,
      "publisher_check": "md5-publisher",   // any kind in the table above; unverified-zip has no digest
      "publisher_url": "https://download.geofabrik.de/…",
      "fetched": "2026-09-22T03:10:41Z",
      "verified": "2026-09-29T03:00:12Z",
      "status": "current",
      "previous": "osm-regions/north-america/us/vermont-latest.osm.pbf.previous"
    }
  ],
  "deferred": [{"unit": "kiwix-library", "reason": "no books selected"}],
  "last_run": {"started": "…", "finished": "…", "fetched": 2, "verified": 40, "failed": 0}
}
```

`status` is one of `current`, `stale` (publisher has a newer version the
schedule has not yet fetched), `failed` (last fetch failed; previous copy
serving), `corrupted` (bytes no longer match; being re-fetched).

`status.html` is the same, readable, at the server root: last run, per unit
counts, the failures with their reasons, disk used, and the licence line for
every unit, because the mirror redistributes on the LAN what each licence
permits and the page says so.

### Serving

A small HTTP server in the Bunker's own process (stdlib `http.server`
subclass with byte-range support, the same thing the engine's tile page
needs), read-only, serving `<root>` with `.incoming`, `.lock` and
`*.previous` hidden. Directory listings off; the index and the status page
are the only navigation. `HEAD` answers with size so the engine can check
before fetching.

The engine's mirror lookup is `<mirror>/<unit>/<name>`; the server maps that
to the path in the index, so the on-disk name (with `-latest`, versions or
tile names) never leaks into the mirror contract.

### Reports and notifications

Each run appends one JSON line to `<root>/.runs.jsonl` and prints a plain
summary to stdout, which the container runtime keeps as its log. `bunker
status` prints the last run and anything not `current`. Webhooks, Matrix and
the like are a later piece and are named in the roadmap, not built.

### Commands

```
bunker run [--all] [--unit NAME]...    one pass now; exit 0 clean, 1 failures, 125 locked
bunker status [--json]                 the last run and what is not current
bunker verify [--unit NAME]...         re-hash every file against its sidecar; nothing fetched
bunker serve                           the HTTP server in the foreground
bunker schedule                        the scheduler: serve + run on the cadence (the container's entrypoint)
bunker doctor                          the engine answers, the volume is writable, the port binds, the config parses
```

Every command takes `--config PATH` (default `/etc/bunker/bunker.toml`, then
`./bunker.toml`) and `--json` where a document exists, following D-059's
envelope shape so the engine's own JSON readers can read it.

### Deployment

- **Image:** Debian 13 slim, non-root user `bunker`, the pinned Hammunition
  release installed from its git tag with a verified archive hash (never
  `pip install` from an unpinned index), the Bunker installed from the
  repo. Entry point `bunker schedule`. Built and published by the GYST
  container-release pipeline to GHCR, signed, with an SBOM.
- **Synology (Container Manager, Docker):** `compose.yaml` in the repo,
  imported as a project: image tag pinned to a release, `/volume1/bunker`
  bound to `/data`, `bunker.toml` bound read-only, port 8080 published on the
  LAN interface, restart unless-stopped, a healthcheck that hits `/index.json`.
- **A Debian host (rootless Podman):** `packaging/bunker.container`, a
  quadlet unit for `systemctl --user`, same mounts, with a note that the
  project's rule is rootless Podman and never the docker group.
- **Updating:** change the image tag in the compose file, redeploy. The
  volume carries the state; the index version is checked on start and an
  older index is upgraded in place, a newer one refuses.

### Security posture

- Non-root in the image; the volume is the only writable path.
- No credentials anywhere: nothing to fetch needs one, and the server has
  no auth because the consumer verifies.
- TLS to every publisher, through the engine's transport; a publisher on
  plain HTTP is whatever the catalog says it is, disclosed in the report.
- The bytes on disk are re-hashed on a cadence; the sidecar is a claim, not
  proof.
- Nothing downloaded is ever executed, unpacked or parsed beyond hashing.
- Serving is on the LAN interface the compose file maps; the docs say never
  to publish the port on an internet-facing interface.
- The test suite blocks every socket except loopback.

### Testing and CI

- `pytest` with a fake `hammunition` on PATH that prints a canned
  `ArtifactsDocument`, a loopback publisher serving files with the right
  and wrong hashes, a temp volume. Tests cover: a first run fetches
  everything; a second run fetches nothing; a corrupted file is re-fetched
  and reported; a failed fetch keeps the previous copy serving; the lock;
  the schedule cadence per unit; the index upgrade; the server's byte
  ranges and hidden paths; `--json` documents match their goldens.
- `mypy --strict`, `ruff`, and the GYST shared CI (`CI green` gate), the
  container build on every tag, weekly a real run against a two-artifact
  public selection to catch a publisher changing shape.
- Falsify each check once before trusting it, per the parent project's rule.

### Licence and branding

GPL-3.0-or-later: the Bunker imports the engine as a library. Copyright
Renegade Penguin LLC. The name, word-mark and README shape are Hammunition's;
the README ends with the same *Support This Project* table and *Author &
Socials* card as Hammunition's, verbatim, icons copied into `media/icons/`.

### Roadmap, not in the first cut

- Notifications (Matrix, Discord webhook, email).
- Push to a field machine over SSH.
- Mirroring the derived outputs (Navit maps, Garmin images, Routino
  databases) so a field machine can skip conversion: needs the engine to
  treat a derived output as an artifact with a hash, which it does not yet.
- More than one selection (per-machine profiles) on one volume.
- A `hammunition doctor` line that says whether the configured mirror
  answers and how old its index is.

## Open questions

None blocking. The engine-side decision number is assigned when the
Hammunition PR is opened.
