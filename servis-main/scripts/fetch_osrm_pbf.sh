#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$ROOT_DIR/data/osm"
mkdir -p "$DATA_DIR"

PBF_URL=${1:-"http://download.geofabrik.de/europe/turkey/marmara/istanbul-latest.osm.pbf"}
OUT_FILE="$DATA_DIR/region.osm.pbf"

echo "Downloading PBF from: $PBF_URL"
curl -L "$PBF_URL" -o "$OUT_FILE"
echo "Saved to: $OUT_FILE"
