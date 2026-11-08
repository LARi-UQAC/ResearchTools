"""
build_kit.py - assemble the distributable aider kit from the live configuration.

Copies every file the manual references into a clean tree, replaces every
machine-specific path with a {{HOME}} placeholder that the kit's own setup
script substitutes, generalises the hardware statement, and refuses to finish
if any personal identifier survives.
"""

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import kit_manifest

HOME = pathlib.Path.home()
ACCOUNT = HOME.name

# Canonical sources, since 2026-09-24: this build reads the aider-setup skill's
# own tree inside ResearchTools rather than the operator's home directory. That
# is a different question from where the ASSEMBLED kit gets INSTALLED (still
# $HOME on a student's or the operator's machine, on purpose - see
# finish_kit.py / patch_setup.py / newproject_ps1.py, which stay $HOME-based
# because installation genuinely is per-machine). HOME/ACCOUNT above stay in
# use for the personal-data scrub only.
SKILL_ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[5]

# Strings that must never appear in a distributed file.
#
# Measured 2026-09-03: this list existed and was referenced NOWHERE, while the
# docstring above claimed the script "refuses to finish if any personal
# identifier survives". It refused nothing, and the seven-term check lived only
# as a snippet in the test procedure that a person had to remember to run - a
# guard that looks installed and does nothing, which is worse than no guard,
# because it is trusted. verify() below is what the docstring was describing.
#
# On integration this becomes a data file rather than a literal list (R6); it is
# left inline here because the build pipeline is seven entries long and shipping
# a JSON beside it would be the larger change.
FORBIDDEN = [
    ACCOUNT,            # the account name, and so every absolute home path
    "Martin Otis",      # the owner
    "OutilsLogiciels",  # the private workspace
    "ResearchTools",    # the private toolkit
    "RTX A1000",        # the exact GPU
    "31.6",             # the exact RAM figure
    "uqac",             # the institution, which the owner's address carries
]

# Anything shorter than this matches half the English language, and a term that
# matches everything reports everything, which trains a reader to ignore it.
MIN_TERM_LENGTH = 3


def verify(root: pathlib.Path):
    """
    --------------------------------------------------------------------------
    Purpose:
        Find every forbidden term surviving in an assembled kit.

    Inputs:
        root (Path): the assembled kit directory

    Outputs:
        leaks (list): (term, relative path, line number) for every hit
    --------------------------------------------------------------------------
    """
    leaks = []
    for term in FORBIDDEN:
        if len(term) < MIN_TERM_LENGTH:
            raise SystemExit(
                "REFUSED: forbidden term %r is shorter than %d characters, so it "
                "would match indiscriminately" % (term, MIN_TERM_LENGTH))
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = text.lower()
        for term in FORBIDDEN:
            if term.lower() not in lowered:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if term.lower() in line.lower():
                    leaks.append((term, str(path.relative_to(root)), number))
    return leaks


def self_test() -> int:
    """The negative control: prove the finder can report, and can stay silent.

    A leak check that has never been shown to fail is not a check. This plants
    one term of each kind in a scratch tree, requires every one to be found,
    then requires a clean tree to produce nothing.
    """
    failures = []
    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        (root / "sub").mkdir()
        for index, term in enumerate(FORBIDDEN):
            (root / "sub" / ("planted%d.md" % index)).write_text(
                "harmless line\nthis one carries %s in it\n" % term, encoding="utf-8")
        found = {leak[0] for leak in verify(root)}
        for term in FORBIDDEN:
            if term not in found:
                failures.append("planted %r was NOT reported" % term)

    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        (root / "clean.md").write_text(
            "a kit with nothing personal in it at all\n", encoding="utf-8")
        spurious = verify(root)
        if spurious:
            failures.append("clean tree reported %r" % (spurious,))

    for line in failures:
        print("SELF-TEST FAIL:", line)
    if failures:
        return 1
    print("self-test ok: %d planted terms all reported, clean tree silent"
          % len(FORBIDDEN))
    return 0


if sys.argv[1:2] == ["--self-test"]:
    raise SystemExit(self_test())

OUT = pathlib.Path(sys.argv[1])


# Phrases naming the private toolkit, rewritten so the sentence still reads.
#
# RECOVERED 2026-09-03 from the kit shipped on 2026-09-02, which contains these
# exact replacements while this script contains none of them. The build pipeline
# was rescued out of a temporary directory that day and arrived amputated: it
# lost this map AND the use of FORBIDDEN in the same cut, so the rescued script
# could no longer reproduce the artefact it had itself produced, and would have
# published four occurrences of the toolkit's name with nothing said. The
# replacements below are taken from the shipped file rather than invented, which
# is why they are phrases rather than one blind substitution: a bare replace
# turns "calls the ResearchTools script" into "calls the the toolkit script".
#
# Order matters - most specific first.
NEUTRALISE = [
    ("the ResearchTools script", "the toolkit script"),
    ("from ResearchTools",       "from a shared toolkit"),
    ("ResearchTools",            "the toolkit repository"),
]

# Deliberately NOT here: OutilsLogiciels, the account name, the GPU and the RAM
# figure. Each of those appears only inside a path or a hardware sentence that
# is already rewritten wholesale above, and a blind substitution in a path
# produces something that reads like a path and is not one. Anything they do not
# catch is meant to reach verify() and stop the build, so a person decides.


# Every relative path the build declares it will ship. Filled by write(),
# which every copy() goes through, and emitted as a manifest at the end.
DECLARED = set()


def scrub(text: str) -> str:
    """Replace this machine's paths with the placeholder the setup script fills."""
    for private, neutral in NEUTRALISE:
        text = text.replace(private, neutral)
    home_forms = [
        str(HOME).replace("\\", "/"),
        str(HOME).replace("\\", "\\\\"),
        str(HOME),
        f"/c/Users/{ACCOUNT}",
    ]
    for form in home_forms:
        text = text.replace(form, "{{HOME}}")
    text = re.sub(r"C:[\\/]+Users[\\/]+<you>", "{{HOME}}", text)
    text = text.replace("C:/Users/<you>", "{{HOME}}").replace(r"C:\Users\<you>", "{{HOME}}")
    return text


# --- the generated-copy banner (S44) ----------------------------------------
# Nine files in the kit are copies of a file that lives outside it, and nothing
# in eight of them said so, so an edit made to the kit's copy was silently
# discarded at the next build. rules.md is the ninth and is left alone: its own
# generator already states the fact and names an action a student can actually
# take, since rules-local/ ships in the kit and aider-rules-sync.py does too. A
# second banner there would be two statements of one fact.
#
# The wording carries BOTH audiences, because "do not edit" is false for half of
# them: config/*.json and config/*.yml are installed into the student's home by
# setup.ps1 and are theirs to tune. What is true of every one is that the copy
# INSIDE the kit is generated.
# Split so the JSON form does not read "_generated: Generated by ...".
_BANNER_SOURCE = "build/build_kit.py"
_BANNER_BODY = (
    "An edit to this copy inside the kit is discarded at the next build; the"
    " copy setup.ps1 installs into your home is yours to edit."
)

_BANNERED = frozenset((
    "MANUAL.md",
    "CONFIG_OLLAMA.md",
    "config/aider.conf.yml",
    "config/model-settings.yml",
    "config/conventions.md",
    "config/context-budget.json",
    "config/skills.json",
    "examples/robot-planning-prompt.md",
))


def banner_for(rel: str, text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Prepend the generated-copy banner in the comment form the file's own
        format allows. JSON has no comment syntax, so the banner becomes a
        first key beside the _purpose key those files already carry, inserted
        textually rather than by a parse-and-redump that would destroy their
        hand formatting.

    Inputs:
        rel (str): the kit-relative path being written
        text (str): the file's content

    Outputs:
        text (str): the content, bannered if this path is one of the eight
    --------------------------------------------------------------------------
    """
    if rel not in _BANNERED:
        return text
    if rel.endswith(".json"):
        brace = text.index("{")
        return (text[:brace + 1] + chr(10) + '  "_generated": "' + _BANNER_SOURCE
                + ". " + _BANNER_BODY + '",'
                + chr(10) + text[brace + 1:])
    if rel.endswith(".yml"):
        return ("# Generated by " + _BANNER_SOURCE + ". " + _BANNER_BODY + chr(10)
            + "#" + chr(10) + text)
    # Markdown: an HTML comment, so a reader of the rendered manual never sees
    # it and a reader of the file in an editor - the only person who could make
    # the discarded edit - always does.
    return ("<!-- Generated by " + _BANNER_SOURCE + ". " + _BANNER_BODY + " -->"
            + chr(10) + chr(10) + text)


def write(rel: str, text: str) -> None:
    # newline="" on both sides, so line endings survive the copy untouched.
    # Measured 2026-09-04: without it, read_text collapsed the source's LF to \n
    # and write_text expanded it back to CRLF on Windows, so a shipped file with
    # byte-for-byte identical CONTENT hashed differently from its source - 20 044
    # bytes against 20 494, 450 line endings rewritten. The kit stopped rewriting
    # what it ships that same day, and this was the last thing still doing it.
    dst = OUT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(banner_for(rel, scrub(text)), encoding="utf-8", newline="")
    # Every shipped file passes through here, copy() included, so this is the
    # one place that can record what the build DECLARED it would ship. The
    # manifest is what verify-kit-install.ps1 compares the assembled tree
    # against - declared versus on-disk, never tree versus tree, because a
    # leaked file (a __pycache__ artefact, say) is present in the tree and
    # absent from the declaration, and comparing the tree with itself would
    # pass for ever. A literal file count in that script has rotted three
    # times: 31, then 50, then 52.
    DECLARED.add(rel.replace("/", "\\"))


def copy(src: pathlib.Path, rel: str) -> None:
    write(rel, src.read_text(encoding="utf-8", newline=""))


if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)

# --- the manual, with the hardware statement generalised --------------------
manual = (SKILL_ROOT / "MANUAL.md").read_text(encoding="utf-8")
# The manual used to open with a sentence naming this machine's RAM and GPU, and
# this script rewrote it into a generic one. Since 2026-09-05 the manual states no
# machine specifics at all: measured figures live in CONFIG_OLLAMA.md, whose
# measured blocks are templated per student, and the manual tells the reader to
# read the driver's own per-run print instead. So there is nothing left to
# generalise, and what is asserted here is the ABSENCE - the invariant that
# actually matters. A future edit reintroducing a hardware figure fails here,
# naming the string, rather than reaching verify() and failing as an anonymous
# leak report two hundred lines later.
_HARDWARE_STRINGS = ["31.6", "RTX A1000", "6144 MiB"]
_present = [s for s in _HARDWARE_STRINGS if s in manual]
if _present:
    raise SystemExit(
        "REFUSED: MANUAL.md names this machine's hardware: "
        + ", ".join(_present)
        + ".\n  A measured figure belongs in CONFIG_OLLAMA.md, inside a MEASURED"
        + " block\n  so the student receives a template rather than someone"
        + " else's numbers.\n  Otherwise write it as a reference-machine"
        + " description, for example\n  'a 6 GB laptop-class GPU'.")
write("MANUAL.md", manual)

# --- CONFIG_OLLAMA.md, with the measured section BLANKED --------------------
# The source copy on the build machine carries this machine's own numbers, and
# those describe one GPU, one CPU and one amount of RAM. Shipping them would
# hand a student a recommendation that was never measured on their hardware and
# that looks exactly like one that was - the same class of defect as a
# hardcoded path, and a worse one, because a wrong num_gpu is acted on rather
# than noticed. So the block between the markers is replaced by the instruction
# to run the test.
#
# A source that has LOST its markers is a refusal, not a pass-through: without
# them this build would ship the build machine's measurements verbatim.
_CFG_SRC = SKILL_ROOT / "CONFIG_OLLAMA.md"
_RESULTS_BEGIN = "<!-- RESULTS:BEGIN -->"
_RESULTS_END = "<!-- RESULTS:END -->"
if not _CFG_SRC.is_file():
    raise SystemExit(
        "REFUSED: %s is missing, so the kit cannot ship CONFIG_OLLAMA.md.\n"
        "  It is the only place that tells a student which num_ctx, num_gpu and\n"
        "  num_thread to use, and the tuning test it names would have no\n"
        "  documentation." % _CFG_SRC)
_cfg_text = _CFG_SRC.read_text(encoding="utf-8")
if (_RESULTS_BEGIN not in _cfg_text) or (_RESULTS_END not in _cfg_text):
    raise SystemExit(
        "REFUSED: %s carries no RESULTS block.\n"
        "  Expected the markers %s and %s.\n"
        "  Without them this build cannot tell the build machine's own measured\n"
        "  numbers from the surrounding documentation, and would ship them to\n"
        "  students as though they had been measured on their own hardware."
        % (_CFG_SRC, _RESULTS_BEGIN, _RESULTS_END))

# --- measured blocks: the operator's numbers never reach a student ----------
# CONFIG_OLLAMA.md is written on a machine whose card, CPU and memory are not
# the reader's. The BUDGET is shared - it comes from context-budget.json, which
# ships - but a measured decode rate, layer count or VRAM figure is not, and a
# recommendation derived from someone else's hardware looks exactly like one
# derived from yours.
#
# So each measured block carries its own student version rather than this build
# guessing what a blank one should look like:
#
#   <!-- MEASURED:BEGIN <label> -->   the operator's own numbers
#   <!-- MEASURED:TEMPLATE -->        what the student receives instead
#   <!-- MEASURED:END -->
#
# TEMPLATE is optional; without it the student gets a pointer to the test. An
# unmatched BEGIN is a REFUSAL, because the failure mode is shipping the
# operator's measurements silently.
_M_BEGIN = "<!-- MEASURED:BEGIN"
_M_TEMPLATE = "<!-- MEASURED:TEMPLATE -->"
_M_END = "<!-- MEASURED:END -->"
_M_POINTER = ("> Not measured on this machine yet. **Run the test:"
              " `ollama-tune.bat`**\n")


def strip_measured(text: str, origin: str) -> tuple:
    """Replace every measured block with its template half, or with a pointer."""
    out, count, cursor = [], 0, 0
    while True:
        start = text.find(_M_BEGIN, cursor)
        if start < 0:
            out.append(text[cursor:])
            break
        head_end = text.find("-->", start)
        end = text.find(_M_END, start)
        if head_end < 0 or end < 0:
            raise SystemExit(
                "REFUSED: %s has a '%s' with no matching '%s'.\n"
                "  A measured block that is not closed would ship this machine's\n"
                "  own numbers to a student as though they were theirs."
                % (origin, _M_BEGIN, _M_END))
        out.append(text[cursor:start])
        block = text[head_end + 3:end]
        template_at = block.find(_M_TEMPLATE)
        if template_at >= 0:
            out.append(block[template_at + len(_M_TEMPLATE):].strip("\n") + "\n")
        else:
            out.append(_M_POINTER)
        cursor = end + len(_M_END)
        count += 1
    return "".join(out), count


_blanked = (_RESULTS_BEGIN + "\n"
            "\n"
            "Nothing has been measured on this machine yet.\n"
            "\n"
            "**Run the test: `ollama-tune.bat`**\n"
            "\n"
            "It fills this section in with your own numbers when you pass\n"
            "`ollama-tune.bat quick apply`. Until then the recommendation in\n"
            "sections 3 and 4 is arithmetic and reference measurement from other\n"
            "hardware, not a measurement of yours.\n"
            "\n"
            + _RESULTS_END)
_start = _cfg_text.index(_RESULTS_BEGIN)
_end = _cfg_text.index(_RESULTS_END) + len(_RESULTS_END)
_cfg_text = _cfg_text[:_start] + _blanked + _cfg_text[_end:]
_cfg_text, _measured_blocks = strip_measured(_cfg_text, str(_CFG_SRC))
print("CONFIG_OLLAMA.md: results block blanked, %d measured block(s) templated"
      % _measured_blocks)
write("CONFIG_OLLAMA.md", _cfg_text)

# --- configuration ----------------------------------------------------------
copy(SKILL_ROOT / "config/conventions.md", "config/conventions.md")
copy(SKILL_ROOT / "config/model-settings.yml", "config/model-settings.yml")
copy(SKILL_ROOT / "config/context-budget.json", "config/context-budget.json")

# rules.md is GENERATED, never a static copy read off disk: this build
# regenerates it from the canonical .claude/rules/ of the repository this skill
# now lives in, plus this skill's own rules-local/ addendum, so the kit can
# never ship a rules.md that has drifted from the rules ResearchTools actually
# enforces (R1, R2). Written into the skill's own config/ so the checked-in
# copy stays what the last build actually produced.
_rules_out = SKILL_ROOT / "config" / "rules.md"
_sync = subprocess.run(
    [sys.executable, str(SKILL_ROOT / "scripts" / "aider-rules-sync.py"),
     "--out", str(_rules_out)],
    capture_output=True, text=True)
if _sync.returncode != 0:
    raise SystemExit(
        "REFUSED: aider-rules-sync.py could not regenerate rules.md.\n" + _sync.stderr)
rules = _rules_out.read_text(encoding="utf-8")
rules = re.sub(r"^Source: `.*`$", "Source: the rule files named by $AIDER_RULES_SOURCE",
               rules, count=1, flags=re.MULTILINE)
rules = re.sub(r"<sub>source: ([^<]*)</sub>", r"<sub>rule file: \1</sub>", rules)
write("config/rules.md", rules)

# The local rules directory travels with the generated file. Without it a student
# receives the rules frozen and has nowhere to add one of their own: the
# canonical directory does not exist on their machine, and the generated file
# says in its own header not to edit it. Shipping the mechanism is what makes
# that header true rather than a dead end.
rules_local = SKILL_ROOT / "config" / "rules-local"
if rules_local.is_dir():
    for path in sorted(rules_local.glob("*.md")):
        copy(path, "config/rules-local/" + path.name)
else:
    raise SystemExit(
        "REFUSED: %s does not exist. It carries the rules this kit adds on top of\n"
        "  the canonical set, R27 among them, and a kit without it ships a\n"
        "  rules.md whose header promises a way to add rules that is not there."
        % rules_local)

# the aider config, as a template
copy(pathlib.Path(sys.argv[2]), "config/aider.conf.yml")

# --- scripts ----------------------------------------------------------------
copy(SKILL_ROOT / "scripts/aider-plan.ps1", "bin/aider-plan.ps1")

# The driver's pure half, split out of it 2026-09-03 when it passed its own
# 16 000-token ceiling. It is NOT optional: aider-plan.ps1 dot-sources it and
# exits 2 by name when it is absent, so a kit shipped without it installs a
# driver that refuses on its first run. Each of these is a REFUSAL rather than a
# skip, for the reason the skills block below already states - a kit that
# assembles without a file the manual names is a kit whose failure surfaces on a
# student's machine instead of here (R3, R8).
_REQUIRED_SCRIPTS = [
    # (source under ~/.local/bin, destination in the kit, why it has to travel)
    ("aider-plan-core.ps1", "bin/aider-plan-core.ps1",
     "the driver dot-sources it and exits 2 without it"),
    # The GPU probe: measured which (model x context) actually puts layers on the
    # card. Shipped 2026-09-03. Until then it carried 98 offline tests and not one
    # reached a student, while the manual told them to re-measure their own
    # hardware and named no tool for doing it.
    ("aider-gpu-probe.py", "bin/aider-gpu-probe.py",
     "the manual's 'measure your own machine' instruction has no tool without it"),
    ("aider-gpu-probe.json", "bin/aider-gpu-probe.json",
     "the probe reads every number, path and tag from it and defaults none"),
    ("Test/test_aider_gpu_probe.py", "bin/Test/test_aider_gpu_probe.py",
     "the offline checks on the probe, so a student can prove it before trusting it"),
    ("Test/verify-aider-plan.ps1", "bin/Test/verify-aider-plan.ps1",
     "32 checks on the driver, so a student can verify their own installation"),
    # The Ollama tuning test, shipped 2026-09-05. CONFIG_OLLAMA.md is the only
    # place in the kit that tells a student what num_ctx, num_gpu and num_thread
    # to use, and it answers "run the test" - so a kit without the test names a
    # tool that does not exist, which is the defect the GPU probe already had.
    ("aider-thread-probe.py", "bin/aider-thread-probe.py",
     "CONFIG_OLLAMA.md tells the student to run it and it measures every number "
     "that file's recommendation is built from"),
    ("aider-thread-probe.json", "bin/aider-thread-probe.json",
     "the probe reads every number, rung, path and tag from it and defaults none"),
    ("Test/test_aider_thread_probe.py", "bin/Test/test_aider_thread_probe.py",
     "58 offline checks, so a student can prove the probe before trusting a "
     "configuration recommendation that came out of it"),
    ("ollama-tune.ps1", "ollama-tune.ps1",
     "the test itself: it computes the token floor and drives the probe. At the "
     "kit ROOT rather than bin/ because CONFIG_OLLAMA.md names it as the one "
     "thing to run"),
    ("ollama-tune.bat", "ollama-tune.bat",
     "the double-click entry point. A student on a fresh machine has PowerShell's "
     "execution policy in the way, and this bypasses it for one process"),
    # The configurator, shipped 2026-09-05. Without it the tuning test ends with
    # numbers a student has to hand-transcribe into a Modelfile, which is the
    # step most likely to be skipped or mistyped - and a wrong num_ctx is acted
    # on rather than noticed.
    ("aider-ollama-config.py", "bin/aider-ollama-config.py",
     "turns the measured numbers into a tuned Ollama tag and reads the tag back; "
     "without it CONFIG_OLLAMA.md ends in manual transcription"),
    ("Test/test_aider_ollama_config.py", "bin/Test/test_aider_ollama_config.py",
     "offline checks on that decision, provable with no Ollama installed"),
    # MANUAL.md step 7 tells a reader to run the night through this, because the
    # detached form is the one that survives closing the terminal and holds the
    # wake lock. It was documented and not shipped, so the documented way to run
    # an overnight job did not exist on a student's machine.
    # bin/, NOT bin/Test/, on BOTH sides. It is a run helper, and a directory
    # called Test invites a reader to think it is one - and the source used to
    # sit there while the kit shipped it to bin/, so the manual's own command
    # named a path that existed on no machine: right for a student who had run
    # setup.ps1, wrong for the operator who had not.
    ("run-detached.ps1", "bin/run-detached.ps1",
     "step 7 of the manual names it as the way to run a night"),
    # The ten defects of 2026-09-05/06 and a checker for them. Seven were
    # invisible to inspection and visible only to a run, so a student who
    # hits one deserves to be told WHICH rather than left to rediscover it.
    ("aider-defect-check.py", "bin/aider-defect-check.py",
     "tells a reader whether a run hit a known defect"),
    ("aider-defects.json", "bin/aider-defects.json",
     "the registry the checker reads; without it the checker refuses"),
    # The gate for the defect that no parser and no existing check could
    # see: a clause written with embedded double quotes turns the rest of
    # the prompt into a PowerShell comment, and the file still compiles.
    ("Test/verify-audit-prompt.ps1", "bin/Test/verify-audit-prompt.ps1",
     "proves the audit prompts still carry every clause they should"),
    # Ships with the sandbox it guards. Measured 2026-09-06: the reviewer
    # emitted edit blocks for three source files it had never been given, aider
    # added each of them to the chat by itself because --yes answers that
    # prompt too, and it committed them while audit.md stayed empty. A stub
    # reviewer in this suite does exactly that, so the guard is proven able to
    # fire rather than merely present.
    ("Test/verify-audit-sandbox.ps1", "bin/Test/verify-audit-sandbox.ps1",
     "proves a reviewer cannot rewrite the project while auditing it"),
]

for _rel_src, _rel_dst, _why in _REQUIRED_SCRIPTS:
    _src = SKILL_ROOT / "scripts" / _rel_src
    if not _src.is_file():
        raise SystemExit(
            "REFUSED: %s is missing, so the kit cannot ship %s.\n"
            "  Reason it has to travel: %s." % (_src, _rel_dst, _why))
    copy(_src, _rel_dst)

# --- the verifier travels unchanged -----------------------------------------
# It used to be rewritten here: its config path pointed at this machine's build
# copy, which no kit installs, so the shipped copy had to differ from the source
# by one line. That is gone since 2026-09-04. verify-aider-plan.ps1 now takes a
# -Config parameter and resolves the path itself - explicit argument, then the
# build copy, then the installed ~/.aider.conf.yml, then a refusal naming all
# three. One file, one truth, and the copy a student receives is byte-identical
# to the one proven here.
#
# The substitution is deliberately NOT replaced by another one. A build that
# edits what it ships is a build whose artefact was never the thing that was
# tested.

sync = (SKILL_ROOT / "scripts/aider-rules-sync.py").read_text(encoding="utf-8")
sync = re.sub(r"(?m)^DEFAULT_SOURCE = .*$",
              'DEFAULT_SOURCE = ""   # no default: the rules directory is site-specific',
              sync, count=1)
write("bin/aider-rules-sync.py", sync)

# --- the night entry point --------------------------------------------------
# The whole point of these two: a student types one command. aider-night.bat is
# what a person double-clicks or calls from cmd, and it exists separately from
# the .ps1 so that nothing has to be known about execution policy.
copy(SKILL_ROOT / "scripts/aider-night.ps1", "bin/aider-night.ps1")
copy(SKILL_ROOT / "scripts/aider-night.bat", "bin/aider-night.bat")

# --- the skills, and the map from stage to bundle ---------------------------
# Copied rather than pointed at, for the reason skills.json states: a plugin
# cache is rewritten on every update, and a file that vanishes turns every run
# into a refusal at startup.
# --- the worked example ------------------------------------------------------
# A student's hardest step is not running the pipeline, it is writing plans that
# fit inside the token ceilings. This ships one worked planning prompt so the
# shape of a good plan set can be read rather than guessed at. It is an example
# of PLANNING, not of code: nothing in it is executed.
_EXAMPLE = SKILL_ROOT / "EXAMPLE-PROMPT-robot.md"
if not _EXAMPLE.is_file():
    raise SystemExit(
        "REFUSED: the worked example was not found at %s.\n"
        "  README.md and MANUAL.md both point a reader at examples/, so a kit\n"
        "  without it names a directory that does not exist." % _EXAMPLE)
copy(_EXAMPLE, "examples/robot-planning-prompt.md")

# The documents that prompt produced, shipped beside it. The prompt alone shows
# what to ASK for; these show what a plan set that fits the token ceilings
# actually looks like, which is the part a student cannot guess. They are copied
# into a project's docs/superpowers/plans/ to try the example, and are useless
# anywhere else - hence the README beside them saying exactly that.
# Where the worked example is copied FROM. Optional third argument, because
# the default is a live project directory: build while that project is being
# run and the ledger being ticked is the one that ships. Passing a clean
# snapshot is how a build stays reproducible while a night is in progress.
_EXAMPLE_PLANS = (pathlib.Path(sys.argv[3]) if len(sys.argv) > 3
                  else SKILL_ROOT / "examples/robot-planner-plans")
if not _EXAMPLE_PLANS.is_dir():
    raise SystemExit("REFUSED: no example plans at %s" % _EXAMPLE_PLANS)
_WANTED = ["spec.md", "progress.md"] + ["plan%d.md" % n for n in range(1, 8)]
_missing = [n for n in _WANTED if not (_EXAMPLE_PLANS / n).is_file()]
if _missing:
    raise SystemExit(
        "REFUSED: the example plan documents are incomplete at %s.\n"
        "  Missing: %s\n"
        "  examples/robot-planning-prompt.md tells a reader these exist, so a\n"
        "  kit shipping the prompt without its output names files that are not\n"
        "  there." % (_EXAMPLE_PLANS, ", ".join(_missing)))
# The example is copied from a REAL project directory, so if that project has
# been run, its progress.md carries that run's ledger marks and the kit would
# ship a worked example that looks half-finished. A student following it would
# then see the driver skip plans that are already ticked. Refused rather than
# stripped: deciding which marks were the driver's and which were the author's
# is a guess, and restoring the file is one command the operator can make
# deliberately.
_progress = (_EXAMPLE_PLANS / "progress.md").read_text(encoding="utf-8")
_ticked = [ln for ln in _progress.splitlines()
           if ln.startswith("- [x]") or ln.startswith("- [!]")]
if _ticked:
    raise SystemExit(
        "REFUSED: %s/progress.md carries %d ledger mark(s), so that project has"
        " been run and the kit would ship a half-finished example.%s"
        "  first: %s%s"
        "  Restore an unticked progress.md before building."
        % (_EXAMPLE_PLANS, len(_ticked), chr(10), _ticked[0], chr(10)))

for _name in _WANTED:
    copy(_EXAMPLE_PLANS / _name, "examples/robot-planner-plans/" + _name)
write("examples/robot-planner-plans/README.md",
      "# Example plan set - mobile robot path planner\n"
      "\n"
      "**Goal.** Show what a plan set that fits the token ceilings actually\n"
      "looks like, so the shape can be copied rather than guessed at.\n"
      "\n"
      "**Contents.** The nine documents produced by the prompt in\n"
      "`../robot-planning-prompt.md`, and nothing else. No code: the local model\n"
      "writes that overnight from these.\n"
      "\n"
      "## To run this example\n"
      "\n"
      "```powershell\n"
      "# 1. the project, which gets its own .venv\n"
      ".\\new-project.ps1 -Name robot-planner -Root \"$HOME\\projects\"\n"
      "\n"
      "# 2. the example's only third-party dependencies, into THAT .venv\n"
      "& \"$HOME\\projects\\robot-planner\\.venv\\Scripts\\python.exe\" -m pip install matplotlib numpy\n"
      "\n"
      "# 3. the documents, replacing the templates\n"
      "Copy-Item \"$HOME\\.config\\aider\\examples\\robot-planner-plans\\*.md\" `\n"
      "          \"$HOME\\projects\\robot-planner\\docs\\superpowers\\plans\\\" -Force\n"
      "Remove-Item \"$HOME\\projects\\robot-planner\\docs\\superpowers\\plans\\README.md\"\n"
      "\n"
      "# 4. dry-run first, then drop -DryRun to run the night\n"
      "cd \"$HOME\\projects\\robot-planner\"\n"
      "aider-plan.ps1 -DryRun -TestCommand '.\\.venv\\Scripts\\python.exe -m unittest discover -s Test -p \"test_*.py\"'\n"
      "```\n"
      "\n"
      # Step 2 is the one that was missing, in the manual and here. new-project.ps1
      # creates an EMPTY .venv and spec.md declares matplotlib and numpy as the
      # example's only permitted third-party libraries, so without it the suite
      # fails on import before the model writes a line - and a reader reads that
      # as the model failing rather than as an install nobody told them to do.
      "**Step 2 is not optional.** `new-project.ps1` creates an EMPTY `.venv`,\n"
      "and `spec.md` declares matplotlib and numpy as this example's only\n"
      "permitted third-party libraries. Without them the suite fails on `import`\n"
      "before the model has written a line, and that failure reads as the model's\n"
      "fault rather than as a missing install.\n"
      "\n"
      "## Sizes, against their ceilings\n"
      "\n"
      "| File | Tokens | Ceiling |\n"
      "|---|---:|---:|\n"
      "| spec.md | 1397 | 4000 |\n"
      "| progress.md | 457 | 2048 |\n"
      "| plan1.md to plan7.md | 526 to 664 each | 4000 |\n"
      "\n"
      "Every one is well inside its budget. That is the point: the seven-plan\n"
      "split is what keeps each plan, and the code it asks for, inside the\n"
      "ceilings. A plan that does not fit is not a long plan, it is two plans.\n")

# --- the reference solution, optional FOURTH argument -----------------------
#
#     python build_kit.py <out> <conf> [<clean-plans>] [<finished-project>]
#
# What OUR run produced, shipped so a student can compare their overnight result
# against ours rather than only against a green test suite. A passing suite says
# the code does what its tests ask; it says nothing about whether the shape is
# the one we got.
#
# It is deliberately NOT placed under examples/robot-planner-plans/. That
# directory is REFUSED when its ledger carries marks, because a worked example
# must start unticked - and a finished solution is ticked everywhere by
# definition. Putting both in one place would mean choosing which of the two
# gates to give up. So they live apart, and this one's gate is the MIRROR of the
# other: a reference whose ledger still has open steps is a half-finished
# solution and is refused just as loudly.
#
# Optional, because as of 2026-09-06 no run has finished all seven plans with
# the defect checker clean. Shipping a truncated run as "the solution" would
# teach the failure rather than the target. Until one exists, nothing in
# MANUAL.md or README.md may point at this directory: the worked example is
# refused outright when it is missing precisely because the manual names it, and
# earning that refusal for a directory that is optional would be the same defect
# in reverse.
_SOLUTION = pathlib.Path(sys.argv[4]) if len(sys.argv) > 4 else None
_SOLUTION_REL = "examples/robot-planner-solution/"

if _SOLUTION is None:
    print("  no reference solution given (4th argument): "
          + _SOLUTION_REL + " is not shipped")
else:
    if not _SOLUTION.is_dir():
        raise SystemExit("REFUSED: no reference solution at %s" % _SOLUTION)

    _sol_plans = _SOLUTION / "docs/superpowers/plans"
    _sol_progress = _sol_plans / "progress.md"
    if not _sol_progress.is_file():
        raise SystemExit(
            "REFUSED: %s has no docs/superpowers/plans/progress.md, so there is"
            " no ledger to judge it by." % _SOLUTION)

    # The mirror gate. An open step means the run did not finish; a [!] means a
    # step was blocked and stayed blocked. Either way the tree is not a
    # solution, whatever its tests say - and the tests are exactly what would
    # hide it, since an empty test file passes.
    _sol_text = _sol_progress.read_text(encoding="utf-8")
    _open = [ln for ln in _sol_text.splitlines() if ln.startswith("- [ ]")]
    _blocked = [ln for ln in _sol_text.splitlines() if ln.startswith("- [!]")]
    if _open or _blocked:
        raise SystemExit(
            "REFUSED: %s is not a finished solution - %d step(s) still open and"
            " %d blocked.%s  first: %s%s"
            "  Ship a run that completed every plan, or omit the fourth"
            " argument." % (_SOLUTION, len(_open), len(_blocked), chr(10),
                            (_open + _blocked)[0], chr(10)))

    # EVERY file the run produced - code, tests, the plan set, the ledger and
    # the audit reports - and nothing the MACHINE produced.
    #
    # The exclusions are not a shortening of the tree, they are the two things
    # that are not artefacts. A build directory and a virtual environment are
    # rebuilt by new-project.ps1 on the student's own machine. The raw aider
    # transcripts under .logs/ and .aider.chat.history.md are a different
    # matter: they are UTF-16 or very large, and every one of them carries
    # absolute paths naming the account this run happened on. They also never
    # pass through scrub(), so shipping them would route around the leak check
    # that guards every other file here. Excluded for that reason, and it is
    # stated in the README rather than left to be discovered.
    _SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".logs",
                  ".pytest_cache", ".mypy_cache"}
    _SKIP_NAMES = {".aider.chat.history.md", ".aider.input.history",
                   ".aider.tags.cache.v4"}
    _SKIP_SUFFIX = {".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".zip",
                    ".png", ".jpg", ".pdf"}

    _sol_files = []
    for _p in sorted(_SOLUTION.rglob("*")):
        if not _p.is_file():
            continue
        _parts = _p.relative_to(_SOLUTION).parts
        if any(part in _SKIP_DIRS for part in _parts[:-1]):
            continue
        if _p.name in _SKIP_NAMES or _p.name.startswith(".aider."):
            continue
        if _p.suffix.lower() in _SKIP_SUFFIX:
            continue
        _sol_files.append(_p)

    # An EMPTY file is the truncation defect, and it is the one thing that must
    # never ship as a reference: aider writes a file only once it has parsed a
    # complete edit block, so a reply cut short leaves the file created and
    # empty while the suite still passes on the tests that came before it. That
    # is D1 of the defect registry, and it happened twice on 2026-09-06.
    _empty = [p.name for p in _sol_files
              if p.stat().st_size == 0 and p.suffix in (".py", ".json", ".txt")]
    if _empty:
        raise SystemExit(
            "REFUSED: the reference solution carries %d EMPTY file(s): %s%s"
            "  An empty source file is the truncated-reply defect, and a green"
            " suite does not contradict it - an empty test file passes.%s"
            "  Fix the run before shipping it as the answer."
            % (len(_empty), ", ".join(_empty), chr(10), chr(10)))

    if not [p for p in _sol_files if p.suffix == ".py"]:
        raise SystemExit(
            "REFUSED: the reference solution at %s holds no Python file."
            % _SOLUTION)

    # The whole tree, at its own relative paths, so the copy reads the way the
    # student's own project will. The plan set, the ledger and the audit
    # reports arrive with it rather than being lifted out and renamed.
    for _p in _sol_files:
        _rel = _p.relative_to(_SOLUTION).as_posix()
        copy(_p, _SOLUTION_REL + "project/" + _rel)

    _sol_audit = _sol_plans / "audit.md"
    _has_audit = _sol_audit.is_file() and _sol_audit.stat().st_size > 0
    _sol_code = [p for p in _sol_files if p.suffix == ".py"]

    write(_SOLUTION_REL + "README.md",
          "# Reference solution - mobile robot path planner\n"
          "\n"
          "**What this is.** The code one of our own overnight runs produced\n"
          "from the plan set in `../robot-planner-plans/`, on the same local\n"
          "model you are running. It is the run's output, byte for byte, and\n"
          "not a tidied-up version written by hand afterwards.\n"
          "\n"
          "**What it is not.** It is not the right answer. It is A answer, from\n"
          "one model on one night. Where yours differs, the interesting\n"
          "question is which of the two the tests actually pin down and which\n"
          "was free to vary.\n"
          "\n"
          "## How to compare\n"
          "\n"
          "Compare the SHAPE before the lines: how many modules, what each one\n"
          "owns, where the seams fall. A diff will tell you every line that\n"
          "differs and none of that.\n"
          "\n"
          "```powershell\n"
          "# your run against ours, file by file\n"
          "Compare-Object (Get-Content .\\world.py) `\n"
          "               (Get-Content \"$HOME\\.config\\aider\\examples\\robot-planner-solution\\project\\world.py\")\n"
          "```\n"
          "\n"
          "## Contents\n"
          "\n"
          "`project/` is the whole tree the run produced, at the same relative\n"
          "paths your own project uses:\n"
          "\n"
          "| Path | What it holds |\n"
          "|---|---|\n"
          "| `project/*.py`, `project/Test/` | the code and its tests |\n"
          "| `project/docs/superpowers/plans/progress.md` | the finished ledger, every step ticked |\n"
          + ("| `project/docs/superpowers/plans/audit.md` | what the reviewer found, plan by plan |\n"
             if _has_audit else "")
          + "| `project/docs/superpowers/plans/plan*.md` | the plans it worked from |\n"
          + "\n"
          + ("**Read `audit.md` first.** It is the half a finished code base\n"
             "never shows: what a second model objected to, and what was changed\n"
             "because of it. Your own run produces the same file, and comparing\n"
             "the two reviews is more informative than comparing the two code\n"
             "bases.\n"
             if _has_audit else
             "This run shipped no audit report, so no `audit.md` is present.\n")
          + "\n"
          "## What is deliberately not here\n"
          "\n"
          "The raw aider transcripts - `.logs/` and `.aider.chat.history.md` -\n"
          "are excluded. They carry absolute paths naming the machine the run\n"
          "happened on, and they are the only files here that would not pass\n"
          "through this kit's leak check. `.venv/` and `__pycache__/` are\n"
          "excluded too: `new-project.ps1` rebuilds those on your machine.\n"
          "\n"
          "Your own run writes the same transcripts, so nothing about how to\n"
          "read them is lost - only ours.\n")

    print("  reference solution: %d file(s), %d of them Python, from %s%s"
          % (len(_sol_files), len(_sol_code), _SOLUTION,
             "" if _has_audit else " (no audit report)"))

copy(SKILL_ROOT / "config/skills.json", "config/skills.json")

skills_src = SKILL_ROOT / "config/skills"
if skills_src.is_dir():
    for path in sorted(skills_src.rglob("*")):
        if path.is_file():
            copy(path, "config/skills/" + path.relative_to(skills_src).as_posix())
else:
    raise SystemExit(
        "REFUSED: %s does not exist, so -Skills would refuse on every student "
        "machine while the configuration claimed to be installed." % skills_src)

# --- the licence that has to travel with those copies -----------------------
# The skill files are third-party work under the MIT licence, which requires the
# copyright notice and the permission notice to accompany every copy. Shipping
# them without it is a licence breach, not an oversight of style, and it was one
# until 2026-09-03. The notice is written beside the files it covers so a student
# who opens config/skills/ finds it without being told where to look.
_SKILL_LICENCE = HOME / ".claude/plugins/cache/claude-plugins-official/superpowers/6.3.0/LICENSE"
if _SKILL_LICENCE.is_file():
    write("config/skills/LICENSE-superpowers.txt",
          "The files in this directory are copied from the 'superpowers' skill\n"
          "collection and are redistributed here under the licence below.\n"
          "Nothing else in this kit is covered by it.\n"
          "\n"
          "Source: superpowers 6.3.0\n"
          "\n"
          "TWO OF THEM HAVE BEEN MODIFIED, and this notice says so rather than\n"
          "claiming otherwise. The MIT licence permits modification; it requires\n"
          "the copyright and permission notice below to travel with the files,\n"
          "which it does. Stating the change is not a licence requirement but it\n"
          "is the honest thing to do, since a reader comparing these against\n"
          "upstream would otherwise think the difference was corruption.\n"
          "\n"
          "Modified, 2026-09-05, to fit a context budget. Whole sections were\n"
          "REMOVED; not one word was rewritten, so every sentence still present\n"
          "is the author's own:\n"
          "\n"
          "  test-driven-development/SKILL.md            2219 -> 1589 tokens\n"
          "      removed: 'Common Rationalizations', 'Example: Bug Fix',\n"
          "               'Debugging Integration'\n"
          "  test-driven-development/writing-good-tests.md  1774 -> 838 tokens\n"
          "      removed: the prose of 'Principle 1: Name the Break' and\n"
          "               'Principle 2: Exercise the Real Thing'\n"
          "      kept:    both of their 'Gate Function' blocks, gathered under a\n"
          "               'Gate functions' heading\n"
          "\n"
          "Why: these files are read into a local model's context window on every\n"
          "call, and on a 6 GB card every token of context is paid for in model\n"
          "weights that no longer fit on the GPU. The removed sections argue for\n"
          "the practice; this harness enforces it instead, because a test gate\n"
          "stops the run. The gate functions were kept for the same reason: they\n"
          "are checks the model applies, not arguments it has to be persuaded by.\n"
          "\n"
          "Unmodified:\n"
          "  code-reviewer.md, receiving-code-review.md\n"
          "\n"
          "The upstream originals are at the source above if you want the full\n"
          "text, and it is worth reading.\n"
          "\n"
          "----------------------------------------------------------------------\n"
          "\n" + _SKILL_LICENCE.read_text(encoding="utf-8"))
else:
    raise SystemExit(
        "REFUSED: the licence for the copied skill files was not found at %s.\n"
        "  Those files are third-party MIT-licensed work, and the licence must\n"
        "  travel with them. Point this at the licence or remove the skills from\n"
        "  the kit; shipping the copies alone is not an option." % _SKILL_LICENCE)

print("kit assembled at", OUT)

# The refusal the docstring promises. It runs here rather than being left to the
# person following the procedure, because the one thing standing between a
# private path and a student's inbox should not be someone's memory.
leaks = verify(OUT)
if leaks:
    print()
    print("REFUSED: personal data survived into the assembled kit.")
    for term, rel, number in leaks:
        print("  %-16s %s:%d" % (term, rel, number))
    print()
    print("Fix it in the SOURCE under .claude/skills/aider-setup/ of ResearchTools,")
    print("never in this output, which is regenerated on the next build.")
    raise SystemExit(1)
print("leak check: clean, %d terms" % len(FORBIDDEN))

# The declaration manifest, written BESIDE the kit and never inside it: a
# manifest listed in its own manifest is a file that can never be reported
# missing. verify-kit-install.ps1 compares the assembled tree against this.
# replace(), not declare(): this step has just deleted and recreated the kit
# directory, so a manifest left from an earlier build must not survive into
# this one. The three steps that follow add to what is written here.
_manifest = kit_manifest.replace(OUT, DECLARED)
print("declared %d files -> %s" % (len(DECLARED), _manifest))
