#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
PATH="$repo_root/target:$repo_root/build:$PATH"
export PATH
if command -v timeout >/dev/null 2>&1; then deadline=timeout
elif command -v gtimeout >/dev/null 2>&1; then deadline=gtimeout
else printf '%s\n' 'GNU coreutils timeout is required' >&2; exit 2; fi
mkdir -p docs/images
for example in examples/*.lms; do
  echo "rendering $example"
  "$deadline" 300 "${LMCLIENT_LMSCRIPT:-lmscript}" "$example"
done
cp images/*.png docs/images/
