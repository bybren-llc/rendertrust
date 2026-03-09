<!-- Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0. -->
# x402 Protocol Evaluation Spike

**Date**: 2026-03-09
**Author**: System Architect
**Time-box**: 1 hour
**Status**: Complete

---

## 1. What Is x402?

x402 is an open standard for internet-native payments built on HTTP 402 (Payment Required).
Created by Coinbase and released under Apache 2.0, it embeds payment negotiation directly
into the HTTP request/response cycle. No accounts, no API keys, no credit cards.

**Key properties**:

- Zero protocol fees (only nominal blockchain network fees)
- Blockchain-agnostic: EVM (Base, Ethereum, Arbitrum, Optimism), Solana, Algorand, Aptos,
  Hedera, Stellar, Sui
- Stablecoin-first: USDC is the primary asset; any ERC-20/SPL token supported
- Trust-minimizing: facilitator cannot move funds beyond client-authorized amounts
- SDKs: TypeScript, Python (`pip install x402`), Go
- GitHub: `coinbase/x402` -- 5.6k stars, 1.2k forks, Apache 2.0
- Production traction (last 30 days from x402.org): 75.4M transactions, $24.2M volume,
  94K buyers, 22K sellers

## 2. Technical Assessment

### 2.1 Transaction Flow

```
Client                   Resource Server              Facilitator          Blockchain
  |                            |                           |                    |
  |-- GET /compute ----------->|                           |                    |
  |<-- 402 + PaymentRequired --|                           |                    |
  |                            |                           |                    |
  | (sign EIP-3009 auth)       |                           |                    |
  |-- GET /compute + sig ----->|                           |                    |
  |                            |-- POST /verify + sig ---->|                    |
  |                            |<-- verification result ---|                    |
  |                            |                           |                    |
  |                            | (perform compute work)    |                    |
  |                            |                           |                    |
  |                            |-- POST /settle + sig ---->|                    |
  |                            |                           |-- submit tx ------>|
  |                            |                           |<-- confirmation ---|
  |                            |<-- settlement receipt ----|                    |
  |<-- 200 + result + receipt -|                           |                    |
```

The client signs an authorization (e.g., USDC `transferWithAuthorization` via EIP-3009).
The facilitator verifies the signature, then settles on-chain after the server delivers.
The server never touches private keys; the facilitator only broadcasts pre-authorized transfers.

### 2.2 Payment Schemes

| Scheme   | Description                        | Networks              |
|----------|------------------------------------|-----------------------|
| `exact`  | Fixed price per request            | EVM, SVM, Algo, Aptos, Hedera, Stellar, Sui |
| `upto`   | Variable price up to a cap (new)   | EVM, SVM              |

The `upto` scheme is critical for compute: charge based on actual GPU-seconds consumed,
not a flat rate.

### 2.3 Python SDK and FastAPI Middleware

A first-party Python SDK exists on PyPI (`x402 v2.3.0`, MIT, Python 3.10+).
It ships with native FastAPI middleware:

```python
from fastapi import FastAPI
from x402.server import x402ResourceServer
from x402.http import HTTPFacilitatorClient, FacilitatorConfig, PaymentOption
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme

app = FastAPI()
facilitator = HTTPFacilitatorClient(FacilitatorConfig(url="https://x402.org/facilitator"))
server = x402ResourceServer(facilitator)
server.register("eip155:8453", ExactEvmServerScheme())  # Base mainnet

routes = {
    "POST /v1/jobs/submit": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to="0x...", price="$0.10",
                               network="eip155:8453")],
        description="Submit compute job",
    ),
}

@app.middleware("http")
async def x402_mw(request, call_next):
    return await payment_middleware(routes, server)(request, call_next)
```

Also available as ASGI class middleware via `PaymentMiddlewareASGI` for `app.add_middleware()`.

## 3. RenderTrust Relevance

### 3.1 M2M Payments for Edge Nodes

RenderTrust edge nodes perform computational work for requestors. Today, billing flows
through Stripe Connect with credit-based accounting. x402 enables a complementary path:

- **Edge nodes as resource servers**: Each node advertises compute endpoints with x402 pricing
- **Requestors as clients**: AI agents or orchestrators pay per-request with stablecoins
- **No account friction**: New requestors can pay immediately without onboarding
- **Cryptographic payment proof**: Settlement receipts become part of the trust envelope

### 3.2 Complement to Stripe (Not Replacement)

| Channel         | Stripe Connect              | x402                         |
|-----------------|-----------------------------|------------------------------|
| Use case        | Human subscriptions, fiat   | M2M micro-payments, agentic  |
| Settlement      | 2-7 business days           | Seconds (on-chain)           |
| Minimum payment | ~$0.50 (fees make less unviable) | ~$0.001 (network gas only) |
| KYC required    | Yes                         | No                           |
| Chargebacks     | Yes                         | No (pre-authorized)          |

Stripe remains the primary rail for human customers, subscriptions, and fiat.
x402 handles the long tail of M2M micro-transactions where Stripe economics break down.

### 3.3 Trust Fabric Alignment

x402 settlement receipts contain on-chain transaction hashes. These can be embedded in
RenderTrust's trust envelope alongside render proofs, creating a unified chain:
`request -> payment proof -> compute proof -> delivery proof`.

### 3.4 Phase III Stablecoin Roadmap Alignment

The existing roadmap includes stablecoin integration in Phase III. x402 provides a
standards-based path rather than building custom payment infrastructure. Adopting it
earlier (Phase II) for edge node M2M payments would de-risk the Phase III scope.

## 4. Integration Architecture

### 4.1 Where x402 Fits

```
                    +-------------------+
                    |   RenderTrust     |
                    |   Gateway (core/) |
                    +--------+----------+
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+          +--------v--------+
     | Stripe Connect   |          | x402 Middleware  |
     | (billing/)       |          | (gateway/)       |
     |                  |          |                  |
     | - Subscriptions  |          | - Per-job pay    |
     | - Credit packs   |          | - Edge node M2M  |
     | - Fiat invoices  |          | - Agent payments |
     +---------+--------+          +--------+--------+
               |                            |
        Stripe API                  Facilitator (x402.org
                                    or self-hosted)
                                            |
                                    Base / Ethereum / Solana
```

### 4.2 Edge Node Payment Flow

```
AI Agent                   Gateway                  Edge Node              Facilitator
   |                          |                         |                       |
   |-- POST /v1/jobs/submit ->|                         |                       |
   |<-- 402 + pricing --------|                         |                       |
   |                          |                         |                       |
   |-- POST + payment sig --->|                         |                       |
   |                          |-- verify payment ------>|                       |
   |                          |                    (validates sig)              |
   |                          |-- dispatch job -------->|                       |
   |                          |                    (execute compute)            |
   |                          |<-- result + proof ------|                       |
   |                          |-- settle payment ------>|-----> on-chain ------>|
   |                          |<-- receipt -------------|                       |
   |<-- 200 + result + proof--|                         |                       |
```

### 4.3 FastAPI Integration Point

The middleware slots into `core/gateway/` as an additional ASGI middleware layer.
Route-level configuration determines which endpoints accept x402 payments vs.
requiring Stripe-authenticated sessions. Both rails can coexist on the same endpoints
via content negotiation or explicit `X-Payment-Method` headers.

## 5. Risk Assessment

**Pros**:

- Open standard backed by Coinbase (Apache 2.0, not vendor lock-in)
- First-party Python/FastAPI SDK -- no custom protocol work needed
- Zero protocol fees; only ~$0.001 base gas per transaction on Base L2
- `upto` scheme maps naturally to variable compute pricing
- Proven traction: 75M+ transactions processed
- Trust-minimizing design aligns with RenderTrust's security-first principles
- Facilitator can be self-hosted for full sovereignty

**Cons**:

- Protocol is 13 months old (created 2025-02); still evolving rapidly (317 open issues)
- Requires requestors to hold stablecoins (limits audience to crypto-native users initially)
- Self-hosted facilitator adds operational complexity
- Regulatory uncertainty around stablecoin acceptance in some jurisdictions
- `upto` scheme is newer and less battle-tested than `exact`

**Mitigations**:

- Use Coinbase-hosted facilitator initially; self-host later if needed
- Position x402 as opt-in alongside Stripe, not replacing it
- Start with `exact` scheme; adopt `upto` after validation
- Monitor regulatory landscape; x402 is network-agnostic so can pivot assets

## 6. Decision

**Recommendation: EVALUATE in Phase II, target ADOPT for Phase II edge node M2M payments.**

**Rationale**: The technical fit is strong. A first-party FastAPI middleware exists, the
protocol is Apache 2.0, and the `upto` scheme directly addresses variable compute pricing.
However, the protocol is still young (v2.x, 13 months), so a structured evaluation with
a proof-of-concept is warranted before committing to production integration.

**Proposed next steps**:

1. **Phase II Sprint N**: Build a PoC -- single FastAPI endpoint behind x402 middleware
   accepting USDC on Base Sepolia testnet. Validate round-trip latency, error handling,
   and settlement reliability.
2. **Phase II Sprint N+1**: If PoC succeeds, integrate x402 alongside Stripe in the
   gateway for a single edge node compute endpoint (shadow mode: both rails active).
3. **Phase III**: Expand x402 to all edge node endpoints, implement `upto` scheme for
   metered compute, and evaluate self-hosted facilitator.

**ADR**: If the PoC succeeds, create `ADR-XXX-x402-payment-integration.md` to formalize
the dual-rail payment architecture decision.

---

**References**:

- x402 specification: https://github.com/coinbase/x402/tree/main/specs
- Python SDK (PyPI): https://pypi.org/project/x402/
- FastAPI middleware: `python/x402/http/middleware/fastapi.py` in coinbase/x402
- x402.org (metrics, whitepaper): https://x402.org
