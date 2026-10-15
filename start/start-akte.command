#!/bin/bash
# Die Akte starten (macOS: Doppelklick; Linux: ./start/start-akte.command). Die Arbeit macht start/akte.sh.
exec bash "$(dirname "$0")/akte.sh" start "$@"
