"""
driver_deps.py - the real dependencies of local_coder_driver, in a module of their own.

`BridgeDeps` binds the driver to plan_contract, the model resolver, the Ollama bridge and
subprocess. It was moved here byte for byte out of local_coder_driver (Issue #104, owner decision
2026-11-05, cloud split) so that a plan can change how the driver talks to the daemon, for example
by logging each call, while returning only this small file instead of the whole driver. The driver
re-exports the class under its old name, so `local_coder_driver.BridgeDeps` is unchanged.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class BridgeDeps:
    """The real dependencies: plan_contract, the resolver, the bridge and subprocess."""

    def __init__(self, root: Path):
        """Purpose: bind to a repository root. Inputs: root (Path). Outputs: None."""
        import ollama_bridge
        import plan_contract
        import token_count
        self.root = root
        self.ob = ollama_bridge
        self.pc = plan_contract
        self.tc = token_count
        self.tc_config = token_count.load_config()

    def contract(self, plan: Path) -> dict:
        """
        Purpose: validate the plan header and resolve its executor and role.
        Inputs: plan (Path). Outputs: dict with executor and role.
        Raises: plan_contract.PlanError on a broken header.
        """
        tiers = self.pc.load_tiers()
        header = self.pc.validate(plan, self.pc.repository_roots(self.root), tiers)
        resolved = self.pc.resolve(header, tiers, self.pc.default_resolver)
        return {"executor": resolved["executor"], "role": resolved["role"]}

    def tag(self, role: str) -> str:
        """Purpose: the tag the resolver adopted for role. Inputs: role (str). Outputs: str."""
        return self.ob.resolve_model(role)

    def window(self, tag: str, role: str) -> int:
        """Purpose: the measured window of that tag or role. Inputs: tag, role (str). Outputs: int."""
        return self.ob._resolve_num_ctx(tag, role)

    def count(self, text: str) -> int:
        """Purpose: token count used for ceilings and the window check. Inputs: text (str).
        Outputs: int (an estimate is multiplied by the configured margin)."""
        found = self.tc.count_text(text, config=self.tc_config)
        if found.exact:
            return found.tokens
        return int(found.tokens * self.tc.config_value(self.tc_config, "estimate_margin"))

    def generate(self, prompt: str, tag: str, window: int, reserve: int, timeout: float) -> str:
        """
        Purpose: one model call; the exact probe is checked first (R8).
        Inputs: prompt (str), tag (str), window (int), reserve (int), timeout (float).
        Outputs: str, the reply with reasoning stripped.
        Raises: ollama_bridge.BridgeError when the prompt does not fit or the daemon fails.
        """
        self.ob.check_budget(prompt, tag, window, reserve, exact_only=True)
        payload = self.ob.build_payload(prompt, tag, self.ob.DEFAULT_SEED, window, num_predict=reserve)
        response = self.ob._post_generate(payload, timeout)
        return self.ob.strip_reasoning(response.get("response", ""))

    def runner(self, command: list, cwd: Path, timeout: float) -> tuple[int, str]:
        """Purpose: run one test file. Inputs: command (list), cwd (Path), timeout (float).
        Outputs: (exit code, combined output); a timeout is code 124."""
        try:
            done = subprocess.run(command, cwd=cwd, timeout=timeout, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {timeout} s"
        return done.returncode, (done.stdout or "") + (done.stderr or "")
