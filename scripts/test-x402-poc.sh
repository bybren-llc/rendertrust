#!/usr/bin/env bash
# Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0.
#
# x402 PoC test script
# Prerequisites:
#   1. export X402_PAY_TO=0xYourWalletAddress
#   2. export X402_ENABLED=true
#   3. Start the server: uvicorn core.main:app --reload
#   4. Run this script: ./scripts/test-x402-poc.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "=== x402 PoC Test Script ==="
echo "Base URL: $BASE_URL"
echo ""

# Test 1: Pricing endpoint (free, should always work)
echo "--- Test 1: GET /api/v1/x402/pricing ---"
curl -s "$BASE_URL/api/v1/x402/pricing" | python3 -m json.tool
echo ""

# Test 2: Compute endpoint without payment (should return 402)
echo "--- Test 2: POST /api/v1/x402/compute (no payment -- expect 402) ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/v1/x402/compute")
echo "HTTP Status: $HTTP_CODE"
if [ "$HTTP_CODE" = "402" ]; then
    echo "PASS: Correctly returned 402 Payment Required"
else
    echo "INFO: Expected 402, got $HTTP_CODE"
    echo "  (If 200, x402 middleware may not be active -- check X402_ENABLED=true)"
fi
echo ""

# Test 3: Health check
echo "--- Test 3: GET /health ---"
curl -s "$BASE_URL/health" | python3 -m json.tool
echo ""

echo "=== Manual Testing Required ==="
echo "To test actual x402 payment flow:"
echo "  1. Get Base Sepolia testnet USDC from faucet"
echo "  2. Use x402 Python client SDK to sign payment"
echo "  3. Send signed request to POST /api/v1/x402/compute"
echo "  4. Verify settlement on Base Sepolia explorer"
echo ""
echo "See docs/spikes/x402-poc-report.md for details."
