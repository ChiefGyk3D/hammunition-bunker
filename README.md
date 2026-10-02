# Hammunition Bunker

> Your RF arsenal, stockpiled.

Hammunition Bunker keeps a verified copy of
[Hammunition](https://github.com/ChiefGyk3D/Hammunition)'s offline data on a
NAS, fresh on a schedule, and serves it on your LAN. A field laptop's
`hammunition install` then takes its map regions, elevation tiles and
reference files from the machine in the next room instead of the internet,
and checks every byte exactly as it would have from the publisher.

---

## Status: 0.1.0, unreleased — tested here, not yet run on a NAS

Everything below is built and covered by the test suite, which runs the
Bunker against a fake engine and a publisher on loopback. Three things are
not yet true, and each is waiting on something named:

- **The engine side ships in Hammunition v0.16.0**, not yet tagged
  (`hammunition artifacts` and the LAN mirror, D-070). Until it is, CI
  cannot install the pinned engine and is red.
- **The image has never been built.** The Dockerfile refuses to build until
  the engine release's sha256 is filled in, which happens when both are
  released.
- **No NAS has run it.** Synology Container Manager and rootless Podman are
  documented from their documentation, not from a run.

## What this is

A container that does three things on one volume:

1. **Asks the engine what to keep.** `hammunition artifacts --json` lists
   every data artifact the engine would fetch for a selection (map regions,
   a freshness, units). The Bunker holds no catalog, no pins and no
   verifier of its own.
2. **Keeps it fresh and proven.** Each unit has a cadence (`daily`,
   `weekly`, `monthly`, `never`); downloads go through the engine's own
   verified fetch; every file gets a sha256 sidecar; the bytes on disk are
   re-hashed on a cadence, because a sidecar is a claim, not proof. The last
   good copy is kept until the next one verifies.
3. **Serves it on the LAN**, read-only, at `<mirror>/<unit>/<name>`, the
   path the engine asks for. A status page says what is held, what is not
   current and why, and what each publisher's licence permits.

| | Hammunition (the engine) | Hammunition Bunker |
|---|---|---|
| Runs | on a workstation, by hand | on a NAS, on a schedule |
| Owns | the catalog, the pins, the verifier | a volume, a schedule, an index |
| Talks | `hammunition artifacts --json` | HTTP on the LAN, read-only |
| Trusts | the hash in the catalog | nothing; re-hashes what it holds |

## Every check kind the engine emits

Each entry of the engine's `artifacts` document names how its download is
verified (`check`). The Bunker keeps one table of them in code
(`src/bunker/checks.py`, tested against the engine's own list and against
this page) and verifies each exactly as the engine does, through the
engine's own `Fetcher`. A kind that is not in the table is **refused by
name**, with the engine's version, and fails the run: nothing is downloaded
for it and nothing is skipped quietly.

| Check | What is verified | Engine method |
|---|---|---|
| `sha256` | the sha256 Hammunition pins | `Fetcher.fetch` |
| `sha256-publisher` | a sha256 the publisher serves (no unit produces it today) | `Fetcher.fetch` |
| `md5-publisher` | Geofabrik's published MD5 and the exact size the engine listed | `Fetcher.fetch_md5` |
| `etag-md5` | the Copernicus object's single-part ETag (its MD5) and the exact size | `Fetcher.fetch_md5` |
| `sha1-publisher` | the SHA-1 and size in CoMaps' own map index at the pinned commit (the engine calls this weaker than a pinned sha256) | `Fetcher.fetch_sha1` |
| `unverified-zip` | **no digest exists**: the zip's own CRC-32s and the tables the engine's reader needs, by the engine's own check | `Fetcher.fetch_checked` |

Whatever the check, every file gets a sha256 sidecar of its bytes, so the
volume is re-hashed one way. `sha1-publisher` and `unverified-zip` need an
engine newer than the pinned `v0.16.0`; on one that lacks the method the
artifact fails by name, saying which method is missing, and nothing is
downloaded. An engine newer than the release this Bunker's table was written
against is named in the run and by `bunker doctor`.

### Unverified artifacts, held by the maintainer's ruling

`unverified-zip` is the Australian Communications and Media Authority's
radiocommunications register (`acma-register/spectra_rrl.zip`, about 68 MB).
The ACMA publishes no checksum and rebuilds the file daily, so nothing can be
pinned: the only check is that the zip is whole and holds the tables the
engine's reader needs, which catches a damaged download and not an altered
one. The Bunker stores it, records its size and the date it was fetched,
fetches it again on its unit's schedule, runs the engine's structure check
(the zip's CRCs) on every fetch and on `bunker verify`, and `bunker status`,
the status page and `bunker doctor` list it under *Unverified, held by the
maintainer's ruling*.

The register's `client.csv` carries licensees' names and addresses, which the
register's licence bars passing on in a derivative. **Ruling, 2026-10-02:**
a Bunker may hold the file anyway, because the Bunker is for users to download
things and have their repository set up; the engine never opens `client.csv`.
Keep this mirror on your LAN, as you must anyway.

If you do not want client data on your NAS, set `hold_unverified = false`
under `[selection]` in `bunker.toml` (default `true`). The register is then
declined by name in every run, never fetched, and a copy already on the
volume is withdrawn from the index and from serving, but **its file stays on
the NAS until you delete it yourself** (the Bunker never deletes). `bunker doctor` says which unverified artifacts are held and
which way the switch is set.

## What this is not

- **Not a public mirror.** It serves without authentication because every
  consumer verifies every byte. That argument holds on your LAN and nowhere
  else: never publish its port to the internet.
- **Not a second source of truth.** The pins live in Hammunition's catalog.
- **Not an apt mirror.** Packages come from your distribution; this holds data.
- **Not something that runs what it downloads.** Nothing is unpacked,
  converted or executed. Files are hashed and served, and that is all; the one
  exception is the engine's own structure check of an unverified zip, which
  reads its headers and CRCs in place and writes nothing.
- **Not a push service.** The laptop pulls; nothing is copied to it.

---

## Quick start

On a Synology NAS, with Container Manager:

1. Make two folders: `/volume1/bunker` (the volume) and
   `/volume1/docker/bunker` (the config).
2. Copy `config.example.toml` to `/volume1/docker/bunker/bunker.toml` and
   set your regions.
3. Import `compose.yaml` as a project, after changing its `ports` line to
   the NAS's LAN address.

On a Debian host, with rootless Podman: `packaging/bunker.container` is a
quadlet unit; its header is the five commands.

Then, on the laptop:

```
hammunition station set --mirror http://<nas-address>:8080/
```

[`docs/guide.md`](docs/guide.md) is the whole walk-through, including the
folder permissions a Synology share needs, what the status page shows, and
how to check a file by hand.

## Security posture

- **Nothing it holds is trusted by anyone.** The laptop checks every file
  against the digest Hammunition already has; a wrong byte from the Bunker
  costs a fall-back to the publisher, not an install.
- **Nothing it holds is trusted by itself either.** Files are re-hashed
  against their sidecars on a cadence; a mismatch is reported as corrupted,
  withdrawn from serving, and fetched again.
- **Non-root, read-only root filesystem, no capabilities.** The volume is
  the only writable path the Bunker uses.
- **No credentials anywhere.** Nothing it fetches needs one and nothing it
  serves asks for one.
- **No package index at build time.** Python and the engine's dependencies
  come from Debian; the engine comes from its release archive, verified
  against a pinned sha256 before it is unpacked.
- **Served paths are an allow-list** built from the index: the download
  area, the lock, the run log and the previous copies are not hidden, they
  are simply never named.
- **The test suite cannot reach the internet**: every socket except
  loopback is blocked.

## Documentation

| Page | For |
|---|---|
| [`docs/guide.md`](docs/guide.md) | installing on Synology or a Debian host, pointing a laptop at it, reading the status page, checking by hand |
| [`docs/reference.md`](docs/reference.md) | every command, exit code, config key, the volume layout, `index.json` and the `--json` documents |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | running the checks, developing against an unreleased engine, cutting a release |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed, per release |

## Contributing

Pull requests and issues are welcome. `make check` runs what CI runs:
ruff, `mypy --strict` and the test suite. [`CONTRIBUTING.md`](CONTRIBUTING.md)
has the rest.

## Licence

**GPL-3.0-or-later.** The Bunker imports Hammunition's engine as a library,
and the engine is GPL-3.0-or-later. SPDX headers throughout; the licence
text is in [`LICENSE`](LICENSE).

The data it mirrors keeps its own licences: OpenStreetMap extracts under
the ODbL, Copernicus elevation under its own licence, and so on. The status
page prints each unit's licence line, because a mirror redistributes on
your LAN what each licence permits.

---

Copyright (C) 2026 Renegade Penguin LLC. Hammunition Bunker is free software
under GPL-3.0-or-later.

---

## 💝 Support This Project

If you find Hammunition useful, consider supporting continued development.
Everything is also collected at **[support.chiefgyk3d.com](https://support.chiefgyk3d.com)**.

### Recurring Support

<div align="center">
<table>
  <tr>
    <td align="center" width="150">
      <a href="https://patreon.com/chiefgyk3d" title="Patreon">
        <img src="media/icons/patreon.svg" width="36" height="36" alt="Patreon"><br>
        <sub><b>Patreon</b></sub>
      </a>
    </td>
    <td align="center" width="150">
      <a href="https://streamelements.com/chiefgyk3d/tip" title="StreamElements">
        <img src="media/streamelements.png" width="36" height="36" alt="StreamElements"><br>
        <sub><b>StreamElements</b></sub>
      </a>
    </td>
    <td align="center" width="150">
      <a href="https://shop.chiefgyk3d.com/" title="Merch Store">
        <img src="media/icons/merch.svg" width="36" height="36" alt="Merch"><br>
        <sub><b>Merch Store</b></sub>
      </a>
    </td>
  </tr>
</table>
</div>

### Cryptocurrency Tips

<div align="center">
<table>
  <tr>
    <td><img src="media/icons/bitcoin.svg" width="28" height="28" alt="Bitcoin">&nbsp;<b>Bitcoin</b><br><code>bc1qztdzcy2wyavj2tsuandu4p0tcklzttvdnzalla</code></td>
  </tr>
  <tr>
    <td><img src="media/icons/monero.svg" width="28" height="28" alt="Monero">&nbsp;<b>Monero</b><br><code>84Y34QubRwQYK2HNviezeH9r6aRcPvgWmKtDkN3EwiuVbp6sNLhm9ffRgs6BA9X1n9jY7wEN16ZEpiEngZbecXseUrW8SeQ</code></td>
  </tr>
  <tr>
    <td><img src="media/icons/ethereum.svg" width="28" height="28" alt="Ethereum">&nbsp;<b>Ethereum</b><br><code>0x554f18cfB684889c3A60219BDBE7b050C39335ED</code></td>
  </tr>
  <tr>
    <td><img src="media/icons/solana.svg" width="28" height="28" alt="Solana">&nbsp;<b>Solana</b><br><code>5T8h3HbyvHgLxwXgchRYbHSqRjZyAr8J7uwjLN9Fh8Jh</code></td>
  </tr>
</table>
</div>

---

## 👤 Author & Socials

<div align="center">
<table>
  <tr>
    <td align="center" width="90"><a href="https://social.chiefgyk3d.com/@chiefgyk3d" title="Mastodon"><img src="media/icons/mastodon.svg" width="30" height="30" alt="Mastodon"><br><sub>Mastodon</sub></a></td>
    <td align="center" width="90"><a href="https://bsky.app/profile/chiefgyk3d.com" title="Bluesky"><img src="media/icons/bluesky.svg" width="30" height="30" alt="Bluesky"><br><sub>Bluesky</sub></a></td>
    <td align="center" width="90"><a href="https://twitch.tv/chiefgyk3d" title="Twitch"><img src="media/icons/twitch.svg" width="30" height="30" alt="Twitch"><br><sub>Twitch</sub></a></td>
    <td align="center" width="90"><a href="https://www.youtube.com/channel/UCvFY4KyqVBuYd7JAl3NRyiQ" title="YouTube"><img src="media/icons/youtube.svg" width="30" height="30" alt="YouTube"><br><sub>YouTube</sub></a></td>
    <td align="center" width="90"><a href="https://kick.com/chiefgyk3d" title="Kick"><img src="media/icons/kick.svg" width="30" height="30" alt="Kick"><br><sub>Kick</sub></a></td>
    <td align="center" width="90"><a href="https://www.tiktok.com/@chiefgyk3d" title="TikTok"><img src="media/icons/tiktok.svg" width="30" height="30" alt="TikTok"><br><sub>TikTok</sub></a></td>
    <td align="center" width="90"><a href="https://www.instagram.com/chiefgyk3d" title="Instagram"><img src="media/icons/instagram.svg" width="30" height="30" alt="Instagram"><br><sub>Instagram</sub></a></td>
    <td align="center" width="90"><a href="https://www.threads.net/@chiefgyk3d" title="Threads"><img src="media/icons/threads.svg" width="30" height="30" alt="Threads"><br><sub>Threads</sub></a></td>
    <td align="center" width="90"><a href="https://discord.chiefgyk3d.com" title="Discord"><img src="media/icons/discord.svg" width="30" height="30" alt="Discord"><br><sub>Discord</sub></a></td>
    <td align="center" width="90"><a href="https://matrix-invite.chiefgyk3d.com" title="Matrix"><img src="media/icons/matrix.svg" width="30" height="30" alt="Matrix"><br><sub>Matrix</sub></a></td>
  </tr>
</table>
</div>

<div align="center"><sub>Made with ❤️ by <a href="https://github.com/ChiefGyk3D">ChiefGyk3D</a></sub></div>
