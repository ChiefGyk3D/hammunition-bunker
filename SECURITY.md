# Security Policy

## Supported versions

The latest tagged release is supported (currently v0.1.0). Fixes land on
`main` and ship in the next tag; older tags are not patched.

## Reporting a vulnerability

Please report security issues **privately**, not in a public issue or pull
request. Use GitHub's private vulnerability reporting on this repository:
[Report a vulnerability](https://github.com/ChiefGyk3D/hammunition-bunker/security/advisories/new).

Please include the affected command, file or configuration key, what you
expected and what happened, and the steps to reproduce it. Do not include a
callsign, grid square, hostname or any other station detail you want kept
private.

## What is in scope

- The Bunker under `src/bunker/`: the fetch and verify run, the volume layout
  and its path-safety checks, the index and sidecars, and the read-only LAN
  server.
- The verification chain: a case where a file is served or kept that did not
  match the digest the engine lists for it.
- The shipped packaging: the container image, `compose.yaml` and the Quadlet
  unit under `packaging/`.

The Bunker serves without authentication over plain HTTP by design, for a LAN
only; reaching it from an untrusted network is a deployment error, not a
vulnerability. Vulnerabilities in the Hammunition engine it imports belong with
[that project](https://github.com/ChiefGyk3D/Hammunition/security/advisories/new).

## What to expect

The Bunker has a sole maintainer. Expect an acknowledgement within a week and a
fix or a written assessment as soon as practical after that. There is no bug
bounty. Reporters are credited in the changelog entry for the fix unless they
ask not to be.
