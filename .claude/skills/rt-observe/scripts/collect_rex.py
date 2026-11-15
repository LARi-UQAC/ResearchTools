"""
collect_rex - the `rex` snapshot section: the numbers behind the watchdog dog.

Rex is the dashboard's picture of the aider watchdog. He needs three things the
other sections do not carry: whether the watchdog program is running (so he is
awake or curled up asleep), the CPU load of the model server, and the load of the
GPU in memory (VRAM) and in compute (CUDA). They are read on the dashboard's own
clock, independent of the watchdog, so the dog can be drawn before the program is
built and the rings keep moving between two of its readings.

Degradation contract of every section here: a reading that cannot be made is None
with its reason in `unread`, never a zero (R8). The CPU figure is the share of ALL
logical processors the model-server processes used between two collections, the
way a task manager shows it; the first collection has no earlier one, so it says
so. Process names come from configuration and are checked before they reach a
command line (R24). Every external call goes through an injected `run` with a
timeout (R10), so the suite needs no process, no GPU and no clock (R19, R21).
"""
import os
import re
import subprocess

_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_PERCENT = 100.0  # a percentage is a unit conversion, not a setting
_LAST = {}        # the previous CPU sample: {"at": epoch seconds, "cpu_s": float}


class ConfigKeyError(KeyError):
    """A configuration key is missing, named by its dotted path (R3)."""


def _cfg(config, *keys):
    """
    --------------------------------------------------------------------------
    Purpose:
        Read one {value, unit, provenance} entry of observe-config.json.
    Inputs:
        config (dict): parsed observe-config.json
        keys (str): the path, for example ("rex", "watchdog_process")
    Outputs:
        value (Any): the entry's "value".
    Raises:
        ConfigKeyError: the path or its value is absent, naming the dotted key.
    --------------------------------------------------------------------------
    """
    node = config
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise ConfigKeyError("observe-config.json declares no %s" % ".".join(keys))
        node = node[key]
    if not isinstance(node, dict) or "value" not in node:
        raise ConfigKeyError("observe-config.json entry %s has no value" % ".".join(keys))
    return node["value"]


def _run(argv, timeout):
    """
    --------------------------------------------------------------------------
    Purpose:
        Run one program and return its standard output.
    Inputs:
        argv (list[str]): the program and its arguments, never a shell string
        timeout (float): seconds before the call is abandoned
    Outputs:
        text (str): standard output.
    Raises:
        OSError: the program is absent. subprocess.TimeoutExpired: too slow.
    --------------------------------------------------------------------------
    """
    done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                          timeout=timeout)
    return done.stdout


def _checked(names):
    """Refuse a process name that is not a plain file name (R24)."""
    for name in names:
        if not _NAME.match(str(name)):
            raise ConfigKeyError("process name %r is not a plain name" % (name,))
    return [str(name) for name in names]


def _watchdog_running(run, image, timeout):
    """True when `tasklist` lists the watchdog image, None when it cannot be asked."""
    try:
        out = run(["tasklist", "/FI", "IMAGENAME eq %s" % image, "/NH", "/FO", "CSV"], timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return image.lower() in out.lower()


def _server_cpu_seconds(run, names, timeout):
    """Total CPU seconds of the model-server processes, 0.0 when none runs, None when unreadable."""
    quoted = ",".join("'%s'" % name for name in names)
    command = ("(Get-Process -Name %s -ErrorAction SilentlyContinue | "
               "Measure-Object -Property CPU -Sum).Sum" % quoted)
    try:
        out = run(["powershell", "-NoProfile", "-Command", command], timeout).strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not out:
        return 0.0
    try:
        return float(out.replace(",", "."))
    except ValueError:
        return None


def _machine_cpu(run, timeout):
    """Whole-machine CPU load in percent, as a task manager reads it, or None."""
    command = ("(Get-CimInstance Win32_Processor | "
               "Measure-Object -Property LoadPercentage -Average).Average")
    try:
        out = run(["powershell", "-NoProfile", "-Command", command], timeout).strip()
        return max(0.0, min(_PERCENT, float(out.replace(",", "."))))
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _gpu(run, timeout):
    """(cuda percent, vram used MB, vram total MB) from nvidia-smi, or None."""
    try:
        out = run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                   "--format=csv,noheader,nounits"], timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    best = None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            cuda, used, total = float(parts[0]), float(parts[1]), float(parts[2])
        except ValueError:
            continue
        if best is None or cuda > best[0]:
            best = (cuda, used, total)
    return best


def collect(config, home, now, run=None, logical_cpus=None):
    """
    --------------------------------------------------------------------------
    Purpose:
        Report whether the watchdog runs and the three loads Rex draws.
    Inputs:
        config (dict): parsed observe-config.json
        home (Path): the home directory, unused here and kept for the section contract
        now (datetime): the injected clock
        run (callable): `run(argv, timeout) -> str`, defaults to a real subprocess
        logical_cpus (int): the processor count, defaults to os.cpu_count()
    Outputs:
        section (dict): status, active, cpu_percent (the model server's share of all
        processors), machine_cpu_percent (the whole machine, as a task manager shows it),
        vram_percent, cuda_percent,
        vram_used_mb, vram_total_mb, logical_cpus, unread {reading: reason},
        proven_by, proven_at.
    Raises:
        ConfigKeyError: a configuration key is absent or a process name is unsafe.
    --------------------------------------------------------------------------
    """
    run = run or _run
    timeout = _cfg(config, "timeouts_seconds", "rex_probe")
    image = _checked([_cfg(config, "rex", "watchdog_process")])[0]
    names = _checked(_cfg(config, "rex", "model_server_names"))
    cpus = logical_cpus or os.cpu_count() or 1
    unread = {}

    running = _watchdog_running(run, image, timeout)
    if running is None:
        unread["active"] = "tasklist could not be run"

    machine_cpu = _machine_cpu(run, timeout)
    if machine_cpu is None:
        unread["machine_cpu"] = "the processor load could not be read"
    cpu_percent = None
    cpu_s = _server_cpu_seconds(run, names, timeout)
    at = now.timestamp()
    if cpu_s is None:
        unread["cpu"] = "the process list could not be read"
    else:
        before = _LAST.get("sample")
        _LAST["sample"] = {"at": at, "cpu_s": cpu_s}
        if before is None or at <= before["at"] or cpu_s < before["cpu_s"]:
            unread["cpu"] = "no earlier sample to compare with"
        else:
            share = (cpu_s - before["cpu_s"]) / (at - before["at"]) / cpus
            cpu_percent = round(max(0.0, min(1.0, share)) * _PERCENT, 1)

    vram_percent = cuda_percent = used = total = None
    gpu = _gpu(run, timeout)
    if gpu is None:
        unread["gpu"] = "nvidia-smi is absent or gave no reading"
    else:
        cuda_percent, used, total = gpu
        vram_percent = round(_PERCENT * used / total, 1) if total else None

    return {"status": "ok", "active": bool(running), "cpu_percent": cpu_percent,
            "machine_cpu_percent": machine_cpu,
            "vram_percent": vram_percent, "cuda_percent": cuda_percent,
            "vram_used_mb": used, "vram_total_mb": total, "logical_cpus": cpus,
            "unread": unread, "proven_by": "tasklist, Get-Process, nvidia-smi",
            "proven_at": now.isoformat(timespec="seconds")}
