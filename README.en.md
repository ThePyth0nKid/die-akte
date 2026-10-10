# Die Akte (“The File”)

**An investigator's evidence board with mandatory sourcing and a signed evidence chain – built for research with AI
agents.**

Agents research fast. Die Akte makes sure nothing becomes a claim unless it is sourced and a human has signed it.
*Agents research, rules advise, the human decides and signs.*

The interface and documentation are in German; this page is a short English overview.

## What it is

An ordinary database with three layers on top:

1. **Rules in the data model.** A thread between two cards (people, companies, authorities, laws …) is a claim with a
   type, time span, statement kind (*sourced*, *suspicion*, *opinion*) and evidence: source, **verbatim quote** and
   location. A check reports what is missing; every rule can be set to *off*, *advice* or *block*.
2. **Evidence layer.** Every source is preserved (original with SHA-256, archive copy, page image, the highlighted
   quote location). Every preservation and every release becomes a signed link in a hash chain in the
   [`atlas-trace-v1`](https://github.com/ThePyth0nKid/atlas) format (Ed25519, BLAKE3, canonical CBOR). Anyone can
   verify it without trusting the server – with `akte pruefe-signaturen` or Atlas' independent verifier.
3. **Output layer.** Deterministic camera flights over the board, rendered frame by frame to video (16:9, 9:16, 1:1),
   optionally with voice, music and highlighted evidence.

Agents (tool tokens, MCP) cannot release, delete or publish anything. Releasing means signing in the browser with a
non-extractable WebCrypto Ed25519 key; blocking findings can be overruled with a justification that is signed too.

## Run it on your machine

Local only – no account, no server, no cost. Install Docker Desktop, download this repository, then double-click
`start\START-AKTE.cmd` (Windows) or `start/start-akte.command` (macOS/Linux). Open <http://localhost:8080/akte>.
Load the fictional demo: `docker compose exec api python manage.py akte_demo`.

## Claude Code (MCP)

```sh
docker compose exec api python manage.py akte_token <account>
claude mcp add akte -e AKTE_BASIS=http://localhost:8080 -e AKTE_TOKEN=<token> \
  -- uvx --from "git+https://github.com/ThePyth0nKid/die-akte#subdirectory=mcp" akte-mcp
```

## Verify the evidence chain

```sh
uv tool install "akte-mcp[beweis] @ git+https://github.com/ThePyth0nKid/die-akte#subdirectory=mcp"
akte pruefe-signaturen --basis http://localhost:8080 --atlas
```

A valid chain proves integrity, authorship by a human key and binding to the exact content – not truth, not the real
identity behind a key, and (until anchoring lands) not the time against a backdating operator. See
[docs/sicherheit.md](docs/sicherheit.md).

## License

AGPL-3.0-or-later for the program (`backend/`, `web/`, `render/`); MIT for `mcp/`, `beweis/`, `skills/`,
`werkzeuge/`; CC BY 4.0 for `docs/`. See `REUSE.toml`. Die Akte does not replace legal review.
