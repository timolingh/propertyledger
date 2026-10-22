#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

docker compose -f docker-compose.yml run --rm propertyledger-web \
  python manage.py check_workflow_test_data

docker compose -f docker-compose.yml run --rm propertyledger-web \
  python manage.py inventory_workflow_release
