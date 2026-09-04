#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

NEW="${1:-}"
if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 X.Y.Z [--push]" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is not clean. Commit or stash first." >&2
  exit 1
fi
OLD=$(tr -d '[:space:]' < VERSION)
if [ "$OLD" = "$NEW" ]; then
  echo "Already at $NEW." >&2
  exit 1
fi

echo "$NEW" > VERSION
sed -i.bak -E "s/\"version\": \"[^\"]+\"/\"version\": \"$NEW\"/" extension/manifest.json
sed -i.bak -E "s/^VERSION = \"[^\"]+\"/VERSION = \"$NEW\"/" helper/main.py
rm -f extension/manifest.json.bak helper/main.py.bak
scripts/check_version.sh

git add VERSION extension/manifest.json helper/main.py
git commit -q -m "Release $NEW"
git tag -a "v$NEW" -m "v$NEW"
echo "Committed and tagged v$NEW ($OLD -> $NEW)."

if [ "${2:-}" = "--push" ]; then
  git push
  git push origin "v$NEW"
else
  echo "Push with: git push && git push origin v$NEW"
fi
