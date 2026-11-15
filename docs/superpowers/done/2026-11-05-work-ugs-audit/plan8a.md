---
executor: local-coder
tier: standard
bounds:
  max_rounds: 3
  max_tokens: 1500000
  plateau: 2
---

# Plan 8a - Attaching images to a bridge request

> **For agentic workers:** run by the local coder model through the driver (rule R39). Return every
> file you create in full. The test file runs as a script (`unittest.main()` at its end) and puts the
> parent folder of its own folder at the start of `sys.path`, then imports the module under test.

**Goal:** a request body for the local daemon can carry images, with no change to the bridge module and
no change to any request that carries none.

**Spec:** `spec.md` D14, "Driver contracts".

## Global Constraints

Python standard library only. The bridge module is not modified (owner rule): images are attached by
this new module after the body is built. The size limit is a parameter, read from configuration by the
caller (R0). Every function carries the Purpose, Inputs and Outputs header, and Raises when it raises
on purpose.

## Review Focus

- No image given: the body serializes byte for byte as before.
- A bad file is refused by position, and the message never holds a path.

---

### Task 1: the module and its tests

**Files:**
- Create: `.claude/skills/loop-engineer/scripts/bridge_images.py`
- Test: `.claude/skills/loop-engineer/scripts/Test/test_bridge_images.py`

**Interfaces:**
- `ImageError` (a `ValueError`).
- `encode_images(files: list[Path], max_bytes: int) -> list[str]`: the base64 text of each file's bytes,
  in order. A missing file, an empty file or one larger than `max_bytes` raises `ImageError` whose
  message names the 1-based position of the file and the reason, never its path.
- `attach_images(payload: dict, files: list[Path] | None, max_bytes: int) -> dict`: returns a copy of
  `payload`. With `None` or an empty list the copy has no `images` key. Otherwise it has an `images`
  key holding `encode_images(files, max_bytes)`. The argument is never changed.

**Tests to write first, each failing before the code exists:**
`test_none_and_empty_list_leave_the_body_byte_identical` (`json.dumps` of the copy equals that of the
original); `test_images_are_base64_of_the_file_bytes_in_order` (two temporary files);
`test_the_argument_is_not_mutated`; `test_missing_file_raises_and_names_the_position`;
`test_oversized_file_raises`; `test_empty_file_raises`; `test_message_never_holds_the_path`.

- Test: `.claude/skills/loop-engineer/scripts/Test/test_bridge_images.py`

- [ ] Step 1: write the tests, run the file, they fail (module absent).
- [ ] Step 2: write the module, run the file, every test passes.
