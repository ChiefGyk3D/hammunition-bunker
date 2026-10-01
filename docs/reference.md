<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Reference

Commands, exit codes, configuration, the volume, `index.json`, the HTTP
interface and the `--json` documents. `tests/test_docs.py` fails when a
command, a configuration key or a document kind is missing from this page.

## Commands

Every command takes `--config PATH` (default `/etc/bunker/bunker.toml`,
then `./bunker.toml`) and, where it has a document, `--json`.

| Command | What it does | `--json` |
|---|---|---|
| `bunker run [--all] [--unit NAME]...` | one pass now: ask the engine, fetch what is due, verify what is held, rewrite the index and the status page | `run` |
| `bunker status` | the last run and everything that is not current, from the index | `status` |
| `bunker verify [--unit NAME]...` | re-hash every held file against its sidecar; nothing is fetched and the engine is not asked | `verify` |
| `bunker serve` | the HTTP server, in the foreground | none |
| `bunker schedule` | the server, plus a pass at start and one a day at `schedule.run_at`; the container's entry point | none |
| `bunker doctor` | the config parses, the engine answers at or above the floor, the volume is writable, the port binds | `doctor` |

`--all` makes every artifact due whatever its cadence; a copy that already
matches is re-hashed, not downloaded again. `--unit NAME` (repeatable)
limits a run to those units and makes them due; a unit the engine does not
list for the selection is an error naming what it does list.

`bunker schedule` re-reads the configuration before each pass, so an edited
selection takes effect at the next pass; a configuration that no longer
parses is reported and the last good one is used. A pass that finds the
volume locked is skipped, not queued.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | clean |
| 1 | the run or check found failures: a failed fetch, a corrupted file, an engine that could not be asked, a doctor check that failed |
| 2 | refused: the configuration, the index (damaged, or newer than this Bunker), the arguments |
| 125 | another run holds the volume's lock |

A run that found a corrupted file exits 1 even when the re-fetch repaired
it: bit rot on the NAS is news. `bunker status` exits 0 whenever it can read
the index; the failures are in what it prints.

## Configuration

`bunker.toml`, TOML. Every key is optional. An unknown table or key is
refused by name. Relative paths resolve against the file's own directory.

| Key | Default | Meaning |
|---|---|---|
| `engine.command` | `"hammunition"` | the engine executable, as a command line or a list of arguments |
| `engine.catalog` | unset | passed to the engine as `--catalog`; the image sets `HAMMUNITION_CATALOG` instead |
| `engine.timeout` | `600` | seconds `hammunition artifacts` may take; it asks publishers for checksums while it lists |
| `selection.map_regions` | `[]` | Geofabrik region paths; none defers the map and terrain units |
| `selection.map_freshness` | `"yearly"` | `yearly`, `monthly` or `latest`, as the engine takes it |
| `selection.reference_books` | `[]` | Kiwix book ids (`hammunition reference books` lists them; D-066). Books are the largest artifacts a Bunker can hold, so unlike `units`, none does not mean "everything": it defers `kiwix-library` as *no books selected*. Needs the Hammunition release that carries #178 (the next release after v0.18.0, until it is tagged) |
| `selection.units` | `[]` | the units to keep; empty is everything the engine lists |
| `storage.root` | `"/data"` | the volume |
| `storage.keep_previous` | `true` | keep the last good copy beside the current one (one, never more) |
| `storage.downloads` | `2` | downloads at a time, 1 to 4 |
| `storage.max_rate` | unset | bytes per second across all downloads of a run: a whole number with `K`, `M` or `G` (powers of 1024), e.g. `"20M"` |
| `schedule.default` | `"weekly"` | refresh cadence: `never`, `daily`, `weekly` or `monthly` |
| `schedule.run_at` | `"03:00"` | when `bunker schedule` runs its daily pass, in the container's local time |
| `schedule.units` | `{}` | a cadence per unit, overriding the default |
| `verify.default` | `"auto"` | how often held files are re-hashed: `auto` (every run under 1 GiB, monthly above), `every-run`, `daily`, `weekly` or `monthly` |
| `verify.units` | `{}` | a verify cadence per unit |
| `serve.bind` | `"0.0.0.0"` | the address the server binds. Inside the container every interface is right: the compose file or quadlet decides the host side. **Outside a container set it to the host's LAN address**; `bunker doctor` says so when it is not |
| `serve.port` | `8080` | the port; the image's healthcheck assumes 8080 |

A cadence is measured from the artifact's last fetch, with an hour's slack
so a daily pass that starts a little early still counts. `never` means "do
not refresh": a missing artifact is fetched on any run.

## What a run does to each artifact

| Found | Action | Status |
|---|---|---|
| not on disk | fetched | `current`, or `failed` |
| on disk, matches what the engine lists | re-hashed when its verify cadence is due (`verified`), else `unchanged` | `current` |
| on disk, bytes no longer match the sidecar (found now, or by an earlier `bunker verify`) | removed and fetched at once (reported as corrupted) | `current`, or `corrupted` if the fetch failed |
| on disk, the engine lists something newer, cadence due | fetched; the old copy becomes `.previous` | `current`, or `failed` with the old copy still served |
| on disk, the engine lists something newer, cadence not due | nothing | `stale` |
| in the index, no longer listed by the engine | dropped from the index (no longer served); files left for you to delete | — |
| deferred by the engine this time | kept as it was | — |

"Matches" means: for a `sha256` or `sha256-publisher` check, the sidecar
equals the engine's digest; for `md5-publisher` and `etag-md5`, the index
records that this copy was verified against the same publisher digest, or,
when it does not (an index moved aside), the file is hashed and compared.
A listed size that disagrees with the file on disk is not a match.

Downloads go through Hammunition's own `Fetcher`: `fetch` for a sha256,
`fetch_md5` for a publisher MD5 with the listed size. A listed artifact with
no digest, or an MD5 with no size, is failed by name and nothing is
downloaded. Any failure the run did not foresee (a truncated body, a disk
error reading a held file) fails that artifact alone, with its type and
message; the rest of the run and its report carry on. A publisher URL on
plain HTTP is named in the report and on the status page. An artifact the
engine lists twice is kept once; twice with different contents, the
second is deferred.

Each run and each `bunker verify` starts by removing the partial downloads
(`*.part.*`) a killed run left in `.incoming`. An artifact whose unit or name could leave the volume (`..`, a
leading `.`, an empty segment) is failed by name.

## The volume

```
<root>/
  index.json                          the index (below)
  status.html                         the status page
  .lock                               one run at a time (flock)
  .runs.jsonl                         one line per run: the run document's body
  .incoming/<unit>/                   downloads in flight, named by the engine's fetch
  <unit>/<name>/<file>                the current copy; <file> is the publisher's file name
  <unit>/<name>/<file>.sha256         its sidecar: "<sha256>  <file>", always sha256
  <unit>/<name>/<old>.previous        the last good copy, and its .sha256
```

One directory per artifact, so a file's dated or `-latest` name never
enters the mirror contract. The one layout clash possible is a name nested
inside another's file (artifact `a` holding file `b`, and artifact `a/b`);
the second to arrive fails by name and the first keeps serving. The sidecar is
sha256 of the bytes whatever the publisher's check was.

## The index

`index.json`, version 1:

| Field | Meaning |
|---|---|
| `kind` | `"bunker-index"` |
| `version` | `1`. An older index is upgraded in place on load; a newer one is refused |
| `generated` | when it was written, UTC |
| `engine.version` | the Hammunition version the last run asked |
| `artifacts` | one entry per artifact held or attempted (below) |
| `deferred` | `{unit, name, reason}` for what the engine could not list |
| `last_run` | `started`, `finished`, `fetched`, `verified`, `failed`, `corrupted`, `stale`, `error`, `plain_http` (the `unit/name` of every artifact whose publisher URL is plain HTTP) |

Each artifact:

| Field | Meaning |
|---|---|
| `unit`, `name` | as the engine lists them; the mirror serves it at `<unit>/<name>` |
| `path` | the current copy, relative to the volume; null when there is none |
| `sha256`, `size` | of the current copy |
| `publisher_check` | `sha256`, `md5-publisher`, `etag-md5` or `sha256-publisher` |
| `publisher_digest` | the digest of that kind the current copy was verified against |
| `publisher_url` | where the engine fetches it |
| `licence` | the unit's licence line |
| `fetched`, `verified` | when it was last downloaded, and last re-hashed |
| `status` | `current`, `stale`, `failed` or `corrupted` |
| `reason` | why the status is not `current`; null when it is |
| `previous` | the last good copy's path, when one is kept |

## HTTP

GET and HEAD only; anything else is 405.

| Path | Serves |
|---|---|
| `/`, `/status.html` | the status page |
| `/index.json` | the index |
| `/<unit>/<name>` | the current copy, mapped through the index: the path the engine asks for |
| `/<path>`, `/<path>.sha256` | the current copy and its sidecar at their volume path, for checking by hand |

Everything else is 404, including `.incoming`, `.lock`, `.runs.jsonl`,
`.previous` copies, directories, and a corrupted entry. HEAD answers with
`Content-Length`. One `Range: bytes=` range is answered 206 with
`Content-Range`; a range past the end is 416; several ranges get the whole
file. No directory listings.

## `--json` documents

One JSON document on stdout, nothing else there; what a command would have
printed goes to stderr. Every document opens with Hammunition's envelope
(D-059):

```json
{"schema": "bunker/1", "kind": "<kind>", "engine": "<bunker version>"}
```

`engine` is the version of the program that wrote the document, the Bunker,
exactly as in Hammunition's own documents; the Hammunition version a run
asked is `engine_version`. A field may be added within `bunker/1`; removing
or changing one bumps the major. `tests/golden/` holds an example of each.

| Kind | From | Fields |
|---|---|---|
| `run` | `bunker run` | `started`, `finished`, `engine_version`, `counts` (fetched, verified, unchanged, stale, failed, corrupted, deferred), `error`, `outcomes` (`unit`, `name`, `action`, `status`, `reason`, `corrupted`, `size`), `deferred`, `dropped`, `plain_http`, `exit_code` |
| `status` | `bunker status` | `engine_version`, `generated`, `last_run`, `counts` (per status), `not_current` (`unit`, `name`, `status`, `reason`), `deferred` |
| `verify` | `bunker verify` | `started`, `finished`, `checked`, `corrupted`, `results` (`unit`, `name`, `path`, `ok`, `reason`), `exit_code` |
| `doctor` | `bunker doctor` | `ok`, `checks` (`name`, `ok`, `detail`) |
| `error` | any command that ended without its own document | `command`, `exit_code`, `message` (everything written to stderr) |

## What the Bunker asks the engine

```
hammunition [--catalog DIR] artifacts --json --map-freshness F [--map-regions R,...] [--units U,...]
```

The answer must be one `artifacts` document with schema `hammunition/1`;
anything else fails the run with what the engine said. An entry with a
`check` this Bunker does not know is reported as deferred, not guessed at.
The contract is Hammunition's `ArtifactsDocument`, described in its
[JSON interface reference](https://github.com/ChiefGyk3D/Hammunition/blob/main/docs/reference/json-interface.md).
