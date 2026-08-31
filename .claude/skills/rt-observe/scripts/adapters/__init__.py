"""
adapters - the harness contract, and the registry that loads them.

Every harness is one small module answering two questions:

    probe(context) -> bool     is this harness present on this machine
    collect(context) -> dict   its state, with receipts

Nothing else. The core knows no harness name; it reads harnesses.json and loads
what that file lists. **Adding a harness is a new module plus one data line, with
no core edit**, and a test asserts exactly that by registering a fake adapter and
checking the snapshot grows.

Zero harnesses is a supported configuration. With no adapter probing true the
snapshot still carries the mirror matrix, the registry, the repo panels and the
plan progression, which is the majority of the value and the whole of it for a
lab member who runs Codex on Linux.
"""
import importlib
import io
import json
import traceback
from pathlib import Path

ADAPTER_DIR = Path(__file__).resolve().parent
SKILL_ROOT = ADAPTER_DIR.parent.parent


class AdapterContext:
    """Everything an adapter may read, injected rather than discovered.

    An adapter never calls Path.home() or reads os.environ for itself: the
    context carries home, the repository root, the parsed config and the clock.
    That is what lets the suite point an entire run at a temporary directory and
    assert the fresh-clone behaviour without touching the real machine (R19, R21).
    """

    def __init__(self, repo_root, home, config, now):
        self.repo_root = Path(repo_root)
        self.home = Path(home)
        self.config = config
        self.now = now

    @property
    def stamp(self):
        return self.now.isoformat(timespec="seconds")


def load_registry(skill_root=None):
    """Read harnesses.json. A missing registry means no adapters, not a crash."""
    path = Path(skill_root or SKILL_ROOT) / "harnesses.json"
    if not path.exists():
        return {"adapters": [], "documented_not_built": []}
    try:
        return json.loads(io.open(path, encoding="utf-8-sig").read())
    except ValueError:
        return {"adapters": [], "documented_not_built": []}


def collect_all(context, skill_root=None, registry=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every registered adapter and gather its state, isolating failures.

    Inputs:
        context (AdapterContext): injected paths, config and clock
        skill_root (Path): where harnesses.json lives; defaults to the skill
        registry (dict): an already-parsed registry, for tests

    Outputs:
        result (dict): {"installed": [...], "absent": [...], "harnesses": {...},
                        "not_built": [...]}
    --------------------------------------------------------------------------
    """
    registry = registry if registry is not None else load_registry(skill_root)
    harnesses = {}
    installed = []
    absent = []

    for entry in registry.get("adapters", []):
        adapter_id = entry.get("id")
        module_name = entry.get("module", adapter_id)
        label = entry.get("label", adapter_id)
        try:
            module = importlib.import_module("adapters.%s" % module_name)
        except ImportError as exc:
            # A registered adapter whose module is missing is NAMED, never
            # dropped: a silently absent harness is the state this whole panel
            # exists to make visible (R3, R8).
            harnesses[adapter_id] = {
                "label": label,
                "status": "unavailable",
                "reason": "adapters/%s.py is registered in harnesses.json but "
                          "could not be imported: %s" % (module_name, exc),
            }
            absent.append(adapter_id)
            continue

        try:
            present = bool(module.probe(context))
        except Exception as exc:                      # noqa: BLE001
            harnesses[adapter_id] = {
                "label": label,
                "status": "unavailable",
                "reason": "probe failed: %s" % exc,
            }
            absent.append(adapter_id)
            continue

        if not present:
            harnesses[adapter_id] = {
                "label": label,
                "status": "not-installed",
                "reason": "%s is not present on this machine; that is a normal "
                          "configuration, not an error" % label,
            }
            absent.append(adapter_id)
            continue

        try:
            state = module.collect(context)
        except Exception as exc:                      # noqa: BLE001
            # One adapter must never take the page down. The failure is reported
            # in its own panel with the exception type, and every other panel is
            # unaffected.
            harnesses[adapter_id] = {
                "label": label,
                "status": "unavailable",
                "reason": "collect failed: %s: %s" % (type(exc).__name__, exc),
                "traceback_tail": traceback.format_exc()[-400:],
            }
            absent.append(adapter_id)
            continue

        state.setdefault("status", "ok")
        state["label"] = label
        harnesses[adapter_id] = state
        installed.append(adapter_id)

    return {
        "installed": sorted(installed),
        "absent": sorted(absent),
        "harnesses": harnesses,
        "not_built": registry.get("documented_not_built", []),
    }
