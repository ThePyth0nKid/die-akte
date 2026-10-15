#!/bin/bash
# Die Akte anhalten (macOS: Doppelklick; Linux: ./start/stop-akte.command). Die Daten bleiben erhalten.
exec bash "$(dirname "$0")/akte.sh" stop "$@"
