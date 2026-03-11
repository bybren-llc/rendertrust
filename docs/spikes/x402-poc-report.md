<!-- Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0. -->
# x402 Protocol PoC Report

**Date**: 2026-03-10
**Author**: System Architect (AI)
**Spike**: REN-65
**Status**: Complete -- Code scaffold delivered, manual testnet validation pending

---

## 1. PoC Scope

Built a complete x402 integration scaffold for RenderTrust's FastAPI gateway:

1. **Middleware wrapper** (`core/gateway/x402/middleware.py`) -- Configures x402 SDK middleware with per-route payment requirements
2. **PoC endpoints** (`core/gateway/x402/routes.py`) -- Compute endpoint behind payment wall + free pricing endpoint
3. **Configuration** -- Settings class extended with x402 env vars (disabled by default)
4. **Test script** (`scripts/test-x402-poc.sh`) -- Manual validation script
5. **Unit tests** -- Verify endpoints work without SDK installed

## 2. Architecture

```text
Client --> FastAPI --> x402 Middleware --> Route Handler --> Response
                          |
                Coinbase Facilitator --> Base Sepolia
```

### Key Design Decisions

- **Soft dependency**: x402 SDK is imported via try/except. If not installed, middleware is simply not added. This prevents the PoC from breaking existing functionality.
- **Feature flag**: `X402_ENABLED=false` by default. Must be explicitly enabled.
- **Separate router**: x402 routes live under `/api/v1/x402/` and do not interfere with existing endpoints.
- **No auth required**: x402 endpoints use payment-based access control, not JWT auth. This is intentional -- the payment IS the authentication for M2M use cases.

## 3. Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `X402_ENABLED` | `false` | Enable x402 middleware |
| `X402_PAY_TO` | `""` | EVM wallet address to receive payments |
| `X402_FACILITATOR_URL` | `https://x402.org/facilitator` | Facilitator service URL |
| `X402_NETWORK` | `eip155:84532` | CAIP-2 chain ID (Base Sepolia) |
| `X402_COMPUTE_PRICE` | `$0.01` | Price per compute request |

## 4. Manual Testing Required

The following cannot be automated without a funded testnet wallet:

1. **402 Response**: With x402 SDK installed and enabled, verify compute endpoint returns 402 with PaymentRequired header
2. **Payment Flow**: Use x402 Python client to sign EIP-3009 authorization, verify facilitator accepts and settles
3. **Settlement**: Verify USDC transfer on Base Sepolia block explorer
4. **Latency**: Measure p50/p95/p99 overhead of x402 middleware

### Prerequisites for Manual Testing

```bash
pip install x402
export X402_ENABLED=true
export X402_PAY_TO=0xYourTestnetWalletAddress
# Get Base Sepolia USDC from faucet
uvicorn core.main:app --reload
./scripts/test-x402-poc.sh
```

## 5. Decision

**GO -- Proceed with Phase II integration** (conditional on manual testnet validation)

### Rationale

- x402 Python SDK exists and provides native FastAPI middleware
- Integration is clean: ~70 LOC middleware wrapper + ~65 LOC routes
- Soft dependency model means zero risk to existing functionality
- `exact` scheme covers MVP pricing needs; `upto` available for metered compute later
- Settlement receipts can be embedded in trust envelope (aligns with core architecture)

### Conditions

1. Manual testnet validation must pass (402 response, payment, settlement)
2. Latency overhead must be <500ms p95
3. Facilitator availability must be >99% over 1-week test period

### Follow-up Issues

- Phase II: Production x402 integration for edge node compute endpoints
- Phase II: Self-hosted facilitator evaluation
- Phase III: `upto` scheme for metered compute pricing

---

## 6. Files Delivered

| File | Type | LOC |
|------|------|-----|
| `core/gateway/x402/__init__.py` | Module init | 14 |
| `core/gateway/x402/middleware.py` | Middleware wrapper | ~90 |
| `core/gateway/x402/routes.py` | PoC endpoints | ~80 |
| `core/config.py` | Settings additions | +5 |
| `core/main.py` | App integration | +12 |
| `scripts/test-x402-poc.sh` | Test script | ~40 |
| `tests/test_x402_poc.py` | Unit tests | ~70 |
| `docs/spikes/x402-poc-report.md` | This report | ~100 |
