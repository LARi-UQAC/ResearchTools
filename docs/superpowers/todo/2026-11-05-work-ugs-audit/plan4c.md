---
executor: local-coder
tier: simple
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 4c - Refuse non-public addresses in the reference check

**Goal:** the reachability check of a reference never contacts the local machine or a private network,
whatever address a student report contains.

**Spec:** `spec.md` threat model (a malicious input file), rule R24, rule R8.

## Global Constraints

Python standard library only. No numeric literal in code (R0): the redirect limit and the timeout come
from the arguments already passed in. A refusal is an explicit result with a reason, never a silent
skip (R8). Fictitious hosts only in tests (R34), with a fake resolver: no network in any test.

## Review Focus

- A host name that resolves to several addresses, one of them private: refused.
- A redirect whose target is private: refused, the first hop being public.
- A numeric host written in an unusual form (decimal, hexadecimal, short dotted): judged by the address
  it resolves to, not by its text.

---

### Task 1: the guard and its tests

**Files:**
- Modify: `.claude/skills/work-ugs-audit/scripts/ref_check.py`
- Test: `.claude/skills/work-ugs-audit/scripts/Test/test_ref_check.py`

**Interfaces:**
- Add `is_public_host(host: str, resolve) -> bool`: `resolve` is a function from a host name to a list of
  address strings. True only when the list is not empty and every address is a global, routable address:
  not loopback, private, link-local, reserved, multicast or unspecified (use the standard `ipaddress`
  module). An unresolvable host is not public.
- Change the default fetch so that it first checks the scheme is `http` or `https`, then checks
  `is_public_host` for the URL's host, and returns a refusal result (not an exception) naming the reason
  when the check fails. It follows redirects itself, one hop at a time, with the same check on every hop
  and the redirect limit taken from the arguments; it never lets the opener follow a redirect on its own.
- The existing `check` and `check_all` keep their signatures; a refused fetch is reported as a distinct
  reachability value, `refused`, in the record they return.

**Tests to write first, each failing before the code exists:**
`test_loopback_host_is_refused`; `test_private_range_host_is_refused`; `test_link_local_host_is_refused`;
`test_public_host_is_allowed`; `test_host_with_one_private_address_is_refused`;
`test_unresolvable_host_is_refused`; `test_redirect_to_a_private_host_is_refused`;
`test_non_http_scheme_is_refused`; `test_refused_fetch_is_reported_as_refused_in_check`.
