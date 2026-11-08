---
executor: local-coder
tier: simple
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4d - Complete the address guard of the reference check

**Goal:** the reachability check connects only to a public address that it has itself validated, and the
list of refused addresses leaves no common bypass.

**Spec:** `spec.md` threat model (a malicious input file), rule R24, rule R8.

## Global Constraints

Python standard library only. No numeric literal in code (R0). A refusal is an explicit result with a
reason (R8). Fictitious hosts only in tests (R34), with a fake resolver and a fake connector: no network in
any test. No comment records reasoning (R103).

## Review Focus

- A shared-address-space host (the carrier-grade NAT range) is refused.
- An address that embeds another one is judged by the embedded address: an IPv4-mapped IPv6 address, a
  6to4 address, a NAT64 address (prefix 64:ff9b::/96).
- The name is resolved once per hop, and the connection goes to the validated address, never to the name
  again: a host that answers a public address first and a private one next cannot reach the private one.

---

### Task 1: the stricter guard and the pinned connection

**Files:**
- Modify: `.claude/skills/work-ugs-audit/scripts/ref_check.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ref_check.py`

**Interfaces:**
- `is_public_host(host, resolve)` keeps its signature. An address is public only when the standard
  `ipaddress` module says it is global. Before that test, an IPv4-mapped, a 6to4 or a NAT64 address is
  replaced by the IPv4 address it embeds, and that one is tested too.
- Add `connect_validated(url: str, resolve, connect, timeout: float) -> object`: resolves the host once, takes
  the first address that passes `is_public_host`, and calls `connect(address, port, host, use_tls, timeout)`
  with the validated ADDRESS, the original host name (for the Host header and the TLS server name) and the
  scheme. It raises a `ValueError` naming the reason when no address passes. `connect` is a parameter so that
  tests need no network.
- The default fetch uses `connect_validated` for every hop, and sends a HEAD request first.

**Tests to write first, each failing before the code exists:**
`test_shared_address_space_is_refused` (100.64.0.1); `test_ipv4_mapped_loopback_is_refused`;
`test_6to4_embedding_a_private_address_is_refused`; `test_nat64_embedding_a_private_address_is_refused`;
`test_nat64_embedding_a_public_address_is_allowed`; `test_connection_goes_to_the_validated_address`;
`test_resolver_is_called_once_per_hop`; `test_no_validated_address_raises_with_the_reason`.
