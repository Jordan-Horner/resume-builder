#!/bin/sh
# Exercise first-run initialization without host credentials or persistent data.
set -eu

image="${1:?Usage: smoke_container.sh IMAGE}"
container=""
cleanup() {
    result=$?
    trap - EXIT
    if [ -n "$container" ]; then
        if [ "$result" -ne 0 ]; then
            docker logs "$container" >&2 || result=1
        fi
        docker rm --force --volumes "$container" >/dev/null || result=1
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

container=$(docker run --detach --health-interval=2s --health-start-period=5s \
    --health-retries=30 "$image")
attempt=0
while [ "$attempt" -lt 60 ]; do
    state=$(docker inspect --format '{{.State.Status}} {{.State.Health.Status}}' "$container")
    case "$state" in
        'running healthy') break ;;
        'running starting') ;;
        *) echo "Container failed startup: $state" >&2; exit 1 ;;
    esac
    attempt=$((attempt + 1))
    sleep 2
done
if [ "$attempt" -eq 60 ]; then
    echo "Container did not become healthy within 120 seconds" >&2
    exit 1
fi

docker exec -i "$container" python - <<'PY'
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8765/api/system/status", timeout=5) as response:
    status = json.load(response)
assert status["status"] == "healthy", status
components = {item["id"]: item["status"] for item in status["components"]}
assert components["portal"] == "online", components
assert components["scheduler"] == "disabled", components
with urlopen("http://127.0.0.1:8765/", timeout=5) as response:
    assert response.status == 200
    assert 'id="root"' in response.read().decode(), "Portal HTML is missing its app root"
print("Fresh container is healthy; portal is served and scheduler is off.")
PY
