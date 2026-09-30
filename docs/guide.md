<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Running a Bunker

The Bunker keeps Hammunition's offline data on a machine that is always on,
and serves it to the machines that are not. This page takes it from nothing
to a laptop installing a map region from it.

**What has been run and what has not.** The Bunker's behaviour is covered by
its test suite: real runs against a fake engine and a real HTTP publisher on
loopback, and Hammunition's own fetch taking a file from the Bunker's server.
The container image has not been built yet (it waits on the engine release,
see [the status](../README.md)), and neither the Synology nor the Podman
steps below have been run end to end. They follow each tool's documented
behaviour; where a step is a guess about a NAS's defaults, it says so.

## What you need

- A machine on your LAN with disk to spare: a Synology NAS with Container
  Manager, or any Debian-family host with rootless Podman. A US state's
  terrain alone can be several gigabytes; a region's map is tens to hundreds
  of megabytes.
- The laptop running Hammunition 0.16.0 or later (`hammunition --version`).

## 1. Choose what to keep

Copy `config.example.toml` to `bunker.toml` and edit `[selection]`:

```toml
[selection]
map_regions = ["north-america/us/vermont", "north-america/us/new-hampshire"]
map_freshness = "yearly"
units = []
```

`map_regions` are Geofabrik region paths, the same ones
`hammunition station set --map-regions` takes (`hammunition maps regions`
lists them). `units = []` keeps everything the engine lists for those
regions: the regions themselves, their terrain tiles, and every `data`
unit. To see exactly what that is before committing a disk to it, run the
engine's own listing on any machine with Hammunition:

```
hammunition artifacts --map-regions north-america/us/vermont
```

**Keep your real selection on the Bunker's machine.** A list of map regions
says where a station is; it does not belong in a repository, an issue or a
forum post.

Then set a cadence per unit if the default (`weekly`) does not suit:

```toml
[schedule]
default = "weekly"
run_at = "03:00"

[schedule.units]
osm-regions = "daily"       # Geofabrik publishes daily
dem-copernicus = "never"    # tiles are pinned; they change with a Hammunition release
```

`never` means "do not refresh", not "do not hold": a missing file is always
fetched. Every key is in [the reference](reference.md#configuration).

## 2a. On a Synology NAS (Container Manager)

1. **Folders.** In File Station, create `bunker` on `volume1` (the volume)
   and `docker/bunker` (the config). Put your `bunker.toml` in
   `docker/bunker`.
2. **Permissions.** The image runs as uid 10001, which owns nothing on a
   Synology share. Either give it the volume, over SSH:

   ```
   sudo chown -R 10001:10001 /volume1/bunker
   ```

   or run the container as your own DSM user instead: find your ids with
   `id` over SSH, and uncomment the `user:` line in `compose.yaml` with
   them. (The default DSM user and group ids vary between installs; the
   `1026:100` in the file is an example, not a value to trust.)
3. **The compose file.** Edit `compose.yaml`'s `ports` line: replace
   `192.0.2.10` with the NAS's LAN address. That address is a documentation
   one and the container fails to start until you do, on purpose: the other
   common choice, `0.0.0.0`, also publishes the port on any interface the
   internet can reach.
4. **Import.** Container Manager → Project → Create. Name it
   `hammunition-bunker`, set the path to `docker/bunker`, choose "Upload
   compose.yaml", and build. The image is pulled from GHCR, pinned to a
   release tag.
5. **Watch the first run.** The container's log (Container → the container →
   Log) shows the server starting and, a moment later, the first pass's
   summary. The first pass downloads everything, so give it time.

**Updating** is the tag: change `image:` in the compose file to the new
release, then Project → Action → Build. The volume carries all the state;
an older index is upgraded in place, and a newer one than the image
understands is refused by name rather than rewritten.

## 2b. On a Debian host (rootless Podman)

The project's rule is **rootless Podman, never the docker group**: membership
in the docker group is root on the host by another name.

```
mkdir -p ~/.config/containers/systemd ~/bunker/data ~/.config/bunker
cp packaging/bunker.container ~/.config/containers/systemd/
cp config.example.toml ~/.config/bunker/bunker.toml    # then edit it
```

Edit `PublishPort=` in `~/.config/containers/systemd/bunker.container` to the
host's LAN address, then:

```
systemctl --user daemon-reload
systemctl --user start bunker
loginctl enable-linger "$USER"
journalctl --user -u bunker -f
```

`UserNS=keep-id` maps your own uid to the image's uid 10001, so
`~/bunker/data` stays yours. `loginctl enable-linger` keeps the service
running after you log out.

Without a container, on a host that already runs Hammunition from a
checkout: `pip install` this repository into the engine's virtual
environment, set `[engine] command` to that environment's `hammunition`
(and `catalog` to the checkout's `catalog/` if it cannot find it), and run
`bunker schedule --config ...` under a systemd user unit of your own.

## 3. Check it

```
docker exec hammunition-bunker bunker doctor
```

(or `podman exec`). Doctor checks four things and says what it found: the
config parses, the engine answers at or above the version this Bunker needs,
the volume is writable, and the port binds or a Bunker already serves on it.

Then open `http://<nas-address>:8080/` in a browser.

## 4. Point a laptop at it

On the laptop:

```
hammunition station set --mirror http://<nas-address>:8080/
hammunition station show
```

From then on every data download asks the Bunker first, at
`<mirror>/<unit>/<name>`, and its publisher on any failure. The plan says
so: `hammunition install --dry-run` opens its data sections with a *Data
mirror* paragraph and names both sources beside each download. To skip the
mirror for one run, `--no-mirror`; to remove it, `--clear-mirror`. The
engine's side is described in Hammunition's own
[LAN mirror guide](https://github.com/ChiefGyk3D/Hammunition/blob/main/docs/guides/lan-mirror.md).

**A mirror does not make an install work offline.** The engine still makes
its plan against the publishers (a region's dated file and MD5 come from
Geofabrik), so with the internet down the plan refuses, mirror or not. The
Bunker saves the download, not the question.

## 5. What the status page shows

`http://<nas-address>:8080/` is `status.html`, rewritten after every run:

- **Last run**: when, and how many artifacts were fetched, verified, stale,
  failed or corrupted; the engine's error, if the run could not ask it.
- **Units**: per unit, how many artifacts are current, stale, failed or
  corrupted, and the space they take.
- **Not current**: every artifact that is not, with the reason. *Stale*
  means the publisher has something newer that the unit's cadence has not
  fetched yet. *Failed* means the last fetch failed; the last good copy, if
  there is one, is still served. *Corrupted* means the bytes on disk no
  longer match their sidecar; the copy is withdrawn and fetched again.
- **Deferred by the engine**: what the engine could not list for this
  selection, and why (a region Geofabrik did not answer for, a unit that
  needs a selection you did not give).
- **Licences**: each unit's licence line. The mirror redistributes on your
  LAN what each licence permits.
- **Disk**: space used on the volume.

`http://<nas-address>:8080/index.json` is the same, for programs;
[the reference](reference.md#the-index) describes it.
`bunker status` prints the same summary in a terminal.

## 6. Check a file by hand

Every file sits beside a sidecar holding its sha256, in the format
`sha256sum -c` reads. On the NAS:

```
cd /volume1/bunker/osm-regions/north-america/us/vermont
sha256sum -c *.sha256
```

From another machine, take any `path` from `index.json` and fetch the file
and its sidecar:

```
curl -fO http://<nas-address>:8080/osm-regions/north-america/us/vermont/vermont-260101.osm.pbf
curl -fO http://<nas-address>:8080/osm-regions/north-america/us/vermont/vermont-260101.osm.pbf.sha256
sha256sum -c vermont-260101.osm.pbf.sha256
```

That proves the file matches what the Bunker wrote. What the *laptop* checks
is stronger: the engine compares against the digest Hammunition pins, or
the publisher's own MD5, never against the sidecar. To re-hash the whole
volume now instead of waiting for the cadence:

```
docker exec hammunition-bunker bunker verify
```

## Security posture

- **Serve on your LAN only.** The Bunker has no authentication and speaks
  plain HTTP. That is safe only because nothing it sends is trusted: the
  laptop checks every byte against a digest it already holds. Publish the
  port on the NAS's LAN address; never on `0.0.0.0` of a machine the
  internet can reach, never through a port forward, never through a
  reverse proxy to the outside.
- **What an attacker on your LAN can do** is serve wrong bytes (the laptop
  rejects them and asks the publisher) or refuse to serve (the laptop asks
  the publisher). What they learn is which public data you mirror, which is
  the same thing your map regions say: part of why the selection stays on
  the NAS.
- **The container runs as a non-root user**, with a read-only root
  filesystem, no Linux capabilities and no privilege escalation; the volume
  is the only writable path the Bunker uses.
- **The image takes nothing from a Python package index.** Debian supplies
  Python and the engine's dependencies; the engine is its release archive,
  verified against a pinned sha256 before it is unpacked.
- **Nothing downloaded is executed, unpacked or parsed** beyond hashing.
- **Downloads use the publishers' own transport** (HTTPS wherever the
  catalog names it), through Hammunition's fetch, which refuses redirects to
  anything that is not HTTP.

## When something is wrong

| Symptom | Meaning | What to do |
|---|---|---|
| `bunker run` exits 125 | another run holds the volume (`.lock`) | wait; the scheduler skips a pass rather than queueing it |
| exit 2, "not an index this Bunker can read" | `index.json` is damaged | move it aside as the message says; the next run re-hashes every file and writes a new one |
| exit 2, "written by a newer Bunker" | the image was rolled back | run the newer release, or move the index aside |
| "the engine answered with schema ..." | the engine is a different major version | use the image's engine, or a Bunker release that reads it |
| everything `stale` | the unit's cadence has not come round | `bunker run --unit NAME` fetches that unit now; `--all` fetches everything due |
| an artifact `failed` with "does not match" | the publisher's bytes are not what the engine lists | nothing to do on the Bunker: the last good copy is still served; the next run tries again |
