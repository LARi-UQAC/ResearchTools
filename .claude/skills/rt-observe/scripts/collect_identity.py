"""
collect_identity - Phase 2 panel: who has an account, mapped to what.

Thin wrapper over rt_store.collect(): the collector contract this skill's core
uses everywhere else, fn(repo_root, home, config, now) -> dict, never raising.
Kept separate from rt_store.py itself so the module that knows PostgreSQL exists
(rt_store.py, per its own docstring) is not also the module wired into
rt_state.section_builders - the same separation collect_services.py keeps from
vault_lock.py.
"""
import rt_store


def collect(repo_root, home, config, now=None, env=None, connector=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report the identity/audit-mapping layer's own state: how many people,
        identifiers and snapshots PostgreSQL holds, or why it cannot answer.

    Inputs:
        repo_root, home (Path): injected roots (R21)
        config (dict): parsed observe-config.json
        now (datetime): injected clock (R19)
        env, connector: injected seams for the offline suite (R21)

    Outputs:
        state (dict): {"status": "ok", "persons", "identifiers", "snapshots",
                       "collected_at"} or {"status": "unavailable", "reason"}
    --------------------------------------------------------------------------
    """
    return rt_store.collect(repo_root, home, config, now=now, env=env,
                            connector=connector)
