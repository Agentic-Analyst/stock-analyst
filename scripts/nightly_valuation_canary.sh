#!/usr/bin/env bash
# Nightly valuation regression: build the deterministic model for a fixed
# basket in the PINNED production worker image, apply the publication
# boundary, and fail loudly if the publish rate collapses or a name errors.
#
# No LLM is called, so a 12-name run costs nothing beyond data-provider
# requests. The image and its environment are exactly production's: the
# compose file's BACKEND_IMAGE digest and /opt/vynn/deploy/api.env.
#
# Install (as root on the worker host):
#   cp scripts/nightly_valuation_canary.sh /opt/vynn/deploy/nightly_valuation_canary.sh
#   cp scripts/valuation_canary_summary.py /opt/vynn/deploy/valuation_canary_summary.py
#   chmod +x /opt/vynn/deploy/nightly_valuation_canary.sh
#   echo '17 3 * * * root /opt/vynn/deploy/nightly_valuation_canary.sh >> /var/log/vynn-canary.log 2>&1' \
#     > /etc/cron.d/vynn-valuation-canary
#
# Results land in /var/lib/vynn/canary/<date>/ (JSON rows + summary), and the
# most recent summary is copied to /var/lib/vynn/canary/latest.txt.
set -euo pipefail

DEPLOY_DIR=${DEPLOY_DIR:-/opt/vynn/deploy}
OUT_ROOT=${OUT_ROOT:-/var/lib/vynn/canary}
BASKET=${BASKET:-"TSLA AMD NVDA META AAPL AMZN GOOGL MSFT CRH MC.PA PYPL PCJEWELLER.NS MU GM TEX BKNG"}
# The basket carries seven names that are withheld by design (see
# scripts/valuation_canary_expectations.json), so five of twelve publish on a
# healthy engine. Three or fewer is the collapse this check exists to catch.
# 5 of 16 publish today; the floor fails if any one of them stops publishing.
MIN_PUBLISH_RATE=${MIN_PUBLISH_RATE:-0.30}

# The pinned worker digest, read from the same compose file api-runner uses.
IMAGE=$(grep -E "^\s*-\s*BACKEND_IMAGE=" "$DEPLOY_DIR/docker-compose.prod.yml" | head -1 | sed -E 's/.*BACKEND_IMAGE=//; s/\s+$//')
if [ -z "$IMAGE" ]; then
  echo "nightly canary: BACKEND_IMAGE not found in $DEPLOY_DIR/docker-compose.prod.yml" >&2
  exit 3
fi

STAMP=$(date -u +%Y-%m-%d)
OUT="$OUT_ROOT/$STAMP"
mkdir -p "$OUT/runs"

echo "=== nightly valuation canary $STAMP  image=$IMAGE ==="
set +e
docker run --rm --name "vynn-canary-$STAMP" --env-file "$DEPLOY_DIR/api.env" \
  -e DATA_PATH=/out -e VYNN_CACHE_DIR=/out/cache \
  --memory 1g --cpus 1 --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 256 \
  -v "$OUT:/out" --entrypoint python "$IMAGE" \
  -m src.valuation_model_canary $BASKET --output-root /out/runs \
  > "$OUT/rows.json" 2> "$OUT/stderr.log"
CANARY_EXIT=$?
set -e

python3 "$DEPLOY_DIR/valuation_canary_summary.py" "$OUT/rows.json" --min-publish-rate "$MIN_PUBLISH_RATE" \
  | tee "$OUT/summary.txt"
SUMMARY_EXIT=${PIPESTATUS[0]}
cp "$OUT/summary.txt" "$OUT_ROOT/latest.txt"

if [ "$CANARY_EXIT" -ne 0 ] || [ "$SUMMARY_EXIT" -ne 0 ]; then
  echo "nightly canary: FAIL (canary exit $CANARY_EXIT, summary exit $SUMMARY_EXIT); see $OUT" >&2
  exit 1
fi
echo "nightly canary: PASS; see $OUT"
