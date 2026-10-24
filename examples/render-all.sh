#!/bin/sh
set -eu

repo_root=`CDPATH= cd -- "`dirname -- "$0"`/.." && pwd`
cd "$repo_root"
mkdir -p docs/images
for example in examples/*.lms; do
  echo "rendering $example"
  timeout 300 lmscript "$example"
done
cp images/*.png docs/images/
