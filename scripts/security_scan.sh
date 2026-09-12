#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
scan_mode=${1:-all}
output_dir=${IPAPER_SECURITY_OUTPUT_DIR:-/tmp/ipaper-security}
tool_dir=${IPAPER_SECURITY_TOOL_DIR:-/tmp/ipaper-security-tools}
audit_image=${IPAPER_AUDIT_IMAGE:-ipaper:v0.8-test}
trivy_version=0.74.0
trivy_sha256=2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a

mkdir -p "$output_dir" "$tool_dir" "$tool_dir/uv-cache" "$tool_dir/trivy-cache"
chmod 0777 "$output_dir" "$tool_dir/uv-cache" "$tool_dir/trivy-cache"

ensure_trivy() {
    if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
        echo "Trivy bootstrap supports the released linux/amd64 platform only" >&2
        return 1
    fi
    local binary="$tool_dir/trivy-$trivy_version"
    if [[ ! -x "$binary" ]]; then
        local archive="$tool_dir/trivy-$trivy_version.tar.gz"
        curl --fail --silent --show-error --location \
            --connect-timeout 30 --max-time 600 --retry 2 \
            "https://github.com/aquasecurity/trivy/releases/download/v${trivy_version}/trivy_${trivy_version}_Linux-64bit.tar.gz" \
            --output "$archive" || return 1
        echo "$trivy_sha256  $archive" | sha256sum --check --status || return 1
        tar --extract --gzip --file "$archive" --directory "$tool_dir" trivy || return 1
        chmod 0755 "$tool_dir/trivy" || return 1
        mv "$tool_dir/trivy" "$binary" || return 1
    fi
    "$binary" --version | grep -F "Version: $trivy_version" >/dev/null || return 1
    printf '%s\n' "$binary"
}

scan_dependencies() {
    docker image inspect "$audit_image" >/dev/null
    local reports=()
    local network_args=()
    # Host-local development proxies need an explicit audit-only network.
    # Runtime services and their outbound policy are unaffected.
    if [[ -n ${IPAPER_AUDIT_NETWORK:-} ]]; then
        network_args=(--network "$IPAPER_AUDIT_NETWORK")
    fi
    local target
    for target in web test worker document; do
        local report="$output_dir/${target}-pip-audit.json"
        reports+=("$report")
        docker run --rm "${network_args[@]}" \
            --volume "$repo_root:/src:ro" \
            --volume "$output_dir:/out" \
            --volume "$tool_dir/uv-cache:/uv-cache" \
            --env UV_CACHE_DIR=/uv-cache \
            "$audit_image" \
            uv tool run --from pip-audit==2.10.1 pip-audit \
            --no-deps --disable-pip \
            --requirement "/src/docker/requirements-${target}.txt" \
            --format json --output "/out/${target}-pip-audit.json" || true
    done
    python3 "$repo_root/scripts/check_pip_audit.py" \
        --exceptions "$repo_root/security/vulnerability-exceptions.json" \
        "${reports[@]}"
}

trivy_ignore_file() {
    local target=$1
    local destination=$2
    python3 - "$repo_root/security/vulnerability-exceptions.json" "$target" "$destination" <<'PY'
import json, pathlib, sys
source, target, destination = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
data = json.loads(source.read_text(encoding="utf-8"))
ids = set()
for entry in data.get("exceptions", []):
    if target in entry["targets"]:
        ids.add(entry["id"])
        ids.update(entry.get("aliases", []))
destination.write_text("\n".join(sorted(ids)) + "\n", encoding="utf-8")
PY
}

scan_filesystem() {
    local trivy
    trivy=$(ensure_trivy)
    "$trivy" filesystem --cache-dir "$tool_dir/trivy-cache" \
        --scanners misconfig,secret \
        --skip-dirs .git --skip-dirs .devnotes --skip-dirs db --skip-dirs papers \
        --skip-files .env --ignore-unfixed --severity HIGH,CRITICAL \
        --format json --output "$output_dir/filesystem-trivy.json" "$repo_root"
    "$trivy" filesystem --cache-dir "$tool_dir/trivy-cache" \
        --scanners misconfig,secret \
        --skip-dirs .git --skip-dirs .devnotes --skip-dirs db --skip-dirs papers \
        --skip-files .env --ignore-unfixed --severity HIGH,CRITICAL \
        --exit-code 1 "$repo_root"
}

scan_images() {
    local trivy
    trivy=$(ensure_trivy)
    local target image ignore_file
    for target in web worker document; do
        case "$target" in
            web) image=${IPAPER_WEB_IMAGE:-ipaper:v0.8-web-smoke} ;;
            worker) image=${IPAPER_WORKER_IMAGE:-ipaper:v0.8-worker-smoke} ;;
            document) image=${IPAPER_DOCUMENT_IMAGE:-ipaper:v0.8-document-smoke} ;;
        esac
        docker image inspect "$image" >/dev/null
        ignore_file="$output_dir/${target}-trivy-ignore.txt"
        trivy_ignore_file "$target" "$ignore_file"
        "$trivy" image --cache-dir "$tool_dir/trivy-cache" \
            --ignore-unfixed --ignorefile "$ignore_file" \
            --format json --output "$output_dir/${target}-trivy.json" "$image"
        "$trivy" image --cache-dir "$tool_dir/trivy-cache" \
            --ignore-unfixed --ignorefile "$ignore_file" \
            --severity HIGH,CRITICAL --exit-code 1 "$image"
        "$trivy" image --cache-dir "$tool_dir/trivy-cache" --format cyclonedx \
            --output "$output_dir/${target}-sbom.cdx.json" "$image"
    done
}

case "$scan_mode" in
    dependencies) scan_dependencies ;;
    filesystem) scan_filesystem ;;
    images) scan_images ;;
    all) scan_dependencies; scan_filesystem; scan_images ;;
    *) echo "usage: $0 [dependencies|filesystem|images|all]" >&2; exit 2 ;;
esac
