#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ledgeros_repo_root="$repo_root/../ledgeros_v2"

if [[ ! -d "$ledgeros_repo_root" ]]; then
  echo "Missing sibling repo at $ledgeros_repo_root." >&2
  echo "The beta reset needs the LedgerOS v2 repo so it can clear both local stacks." >&2
  exit 1
fi

cd "$repo_root"
make reset

pushd "$ledgeros_repo_root" >/dev/null
make reset
popd >/dev/null

