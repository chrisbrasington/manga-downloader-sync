#!/usr/bin/env bash
set -euo pipefail

# Deploy the KOReader Manga Library plugin to a Kobo over SSH.
#
#   ./deploy.sh [user@host]
#
# Defaults to root@192.168.0.43. The Kobo must be reachable on the network and
# running an SSH server on port 22 (the prompt `ssh root@<ip>` must work first).
#
# Copies koreader-plugin/mangalibrary.koplugin/{main.lua,_meta.lua} into
#   /mnt/onboard/.adds/koreader/plugins/mangalibrary.koplugin/

HOST="${1:-root@192.168.0.43}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="mangalibrary.koplugin"
REMOTE_PLUGINS="/mnt/onboard/.adds/koreader/plugins"

# Make sure the files we expect are actually here before touching the device.
for f in main.lua _meta.lua; do
    if [ ! -f "$SRC_DIR/$PLUGIN/$f" ]; then
        echo "error: missing $PLUGIN/$f in $SRC_DIR" >&2
        exit 1
    fi
done

echo "Deploying $PLUGIN -> $HOST:$REMOTE_PLUGINS/"

# Kobo ships busybox (tar/cat, but no guaranteed scp/rsync server). Stream the
# plugin directory as a tarball over ssh and unpack it on the device — this only
# needs a shell + tar on the far end.
tar -C "$SRC_DIR" -cf - "$PLUGIN" \
    | ssh "$HOST" "mkdir -p '$REMOTE_PLUGINS' && tar -C '$REMOTE_PLUGINS' -xf -"

echo "Done. Files on device:"
ssh "$HOST" "ls -l '$REMOTE_PLUGINS/$PLUGIN'"

echo
echo "Restart KOReader on the device to load the changes"
echo "(top menu -> the gear/exit menu -> Restart KOReader)."
