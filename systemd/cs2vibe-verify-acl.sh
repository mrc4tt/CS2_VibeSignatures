#!/bin/sh
# The pipeline writes atomically through mkstemp, so every new snapshot, binary and
# gamedata file is 0600 root. cs2vibe-verify runs unprivileged and needs to read them.
# setfacl -m also widens the ACL mask, so the grant is effective despite the 0600 mode.
set -e
R=/root/CS2_VibeSignatures
setfacl -R -m u:cs2vibe-verify:rX "$R/gamesymbols" "$R/gamedata" "$R/configs" /srv/cs2-binaries
setfacl -m u:cs2vibe-verify:r "$R"/*.py
