# Start the rt-observe dashboard

Thin wrapper over the `rt-observe` skill's launcher. Read
`.claude/skills/rt-observe/SKILL.md` first, then follow it exactly.

This command is a convenience, never the only way in. The dashboard is a plain command line
(`rt-dashboard.ps1`, `rt-dashboard.sh`, `rt-dashboard.bat`, or the VS Code task) precisely
because ResearchTools is cloned by people who do not run Claude Code.

Option contract:

```
/rt-dashboard [--dry-run] [--open] [--port <n>] [--json]
```

Procedure:

1. Parse `$ARGUMENTS`. With no argument, run the dry run FIRST and show its output, because it
   names the interpreter, the bind address, the page and every TTL without starting anything:

   ```powershell
   .\rt-dashboard.ps1 -DryRun
   ```

2. With `--json`, do not start a server at all. The one-shot dump answers instead, and it is
   the right tool inside a script or when the question is only "is anything lost":

   ```powershell
   python .claude/skills/rt-observe/scripts/rt_state.py --json
   ```

3. To serve, hand the command to the user rather than blocking this session on it. The server
   runs in the foreground until Ctrl+C, so a session that starts it stops being able to do
   anything else:

   ```powershell
   .\rt-dashboard.ps1 -Open
   ```

   Report the loopback URL it prints. The session token is printed on the same lines and is
   needed only for an action; it is embedded in the served page, so a person clicking in the
   browser never types it.

4. Read the three refusals back to the user when one fires, rather than working around it:

   - **no interpreter found** names every candidate it tried and exits 2. Fix the environment
     (`.\setup.ps1 -InstallPython`), never point the launcher elsewhere.
   - **the port is held by something else** names the holding PID and exits 1. Free that port or
     pass `--port`. Do not bind a second port: two dashboards showing two different snapshots
     is worse than none.
   - **a dashboard is already running** prints its URL and exits 0. Open that one.

5. Exit codes mean something (R12): 0 clean, 1 something is `lost` or `stale` (for `--json`) or
   the port is held (for `--serve`), 2 a refusal by design. Do not paper over a 1 by re-running.

Never edit an agent, a skill or a hook from the dashboard, and never treat its action buttons as
this command's business: the panel reports and recovers, it does not author.
