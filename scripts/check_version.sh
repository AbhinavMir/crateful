#!/usr/bin/env bash
# Fail if VERSION, extension/manifest.json, and helper/main.py disagree.
set -e
cd "$(dirname "$0")/.."
v_file=$(tr -d '[:space:]' < VERSION)
v_manifest=$(python3 -c 'import json;print(json.load(open("extension/manifest.json"))["version"])')
v_helper=$(grep -E '^VERSION = ' helper/main.py | sed -E 's/VERSION = "(.*)"/\1/')
if [ "$v_file" != "$v_manifest" ] || [ "$v_file" != "$v_helper" ]; then
  echo "Version mismatch: VERSION=$v_file manifest=$v_manifest helper=$v_helper" >&2
  exit 1
fi
echo "Version OK: $v_file"
