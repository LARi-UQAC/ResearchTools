# Privacy guard, extra scan - installed by install-git-hooks.ps1, read by privacy-lib.sh.
#
# Purpose: two checks no betterleaks rule can make.
#   T  a term of the machine-local deny list (real student names, data folders) in an
#      added line, a changed file path, a commit message or a commit author line. The list
#      is never committed: publishing it would be the leak it prevents.
#   P  an absolute drive path in an added line of a test or fixture file, the way a real
#      run's output reaches a fixture (measured 2026-10-12, ResearchTools PR #69).
# Input (stdin): diff text, as `git diff --cached -U0` or `git log -p -m -U0
#   --pretty=medium` print it. Output: one "<kind><TAB><where>" line per finding, never
#   the matched line or term, plus one "N<TAB><count>" line: how many usable terms were
#   loaded, so the caller can say that a list holds none. Exit 0 always on success.
# Variables (-v): termfiles ("|"-separated deny-list files), minlen (shortest term kept),
#   pathmode (off | warn | refuse, "off" skips check P), allowfile (regexes, one per line,
#   an absolute path matching one is not reported).
# A line carrying "betterleaks:allow" is skipped, like every other privacy check.
# A path is checked only while it is ADDED or MODIFIED: deleting or renaming away a leaked
#   path is the remediation and must pass (Issue #70, H2), like removing a leaking line.

# A term is a name, so its boundary is a LETTER, not a word character: "data_name_run",
# "name2024" and "DataName" all contain the name, while "nameville" and "unnamed" do not.
# A lower-to-upper case change counts as a boundary (CamelCase). Matching is byte-wise
# with ASCII-only case folding, so an upper-case accented spelling is a known limit.
function token_hit(line, l, name,    n, s, p, pos, before, after, first, last, lok, rok) {
    n = length(name); s = 1
    while ((p = index(substr(l, s), name)) > 0) {
        pos = s + p - 1
        before = (pos > 1) ? substr(line, pos - 1, 1) : ""
        after = substr(line, pos + n, 1)
        first = substr(line, pos, 1); last = substr(line, pos + n - 1, 1)
        lok = (before !~ /[A-Za-z]/) || (before ~ /[a-z]/ && first ~ /[A-Z]/)
        rok = (after !~ /[A-Za-z]/) || (last ~ /[a-z]/ && after ~ /[A-Z]/)
        if (lok && rok) return 1
        s = pos + 1
    }
    return 0
}

# The line is lowercased once here, not once per term.
function any_term(text,    i, low) {
    low = tolower(text)
    for (i = 1; i <= nterms; i++) if (token_hit(text, low, terms[i])) return 1
    return 0
}

function emit(kind, where,    key) {
    key = kind "\t" where
    if (!(key in seen)) { seen[key] = 1; print key }
}

# The path of a file header is reported unless the file is deleted: the verdict waits for
# the first hunk, the "deleted file mode" line or "+++ /dev/null", whichever comes first.
function flush_path() {
    if (pend != "" && !pend_del && any_term(pend)) emit("T", pend)
    pend = ""; pend_del = 0
}

function load_lines(path, arr, isterm,    line, n, first) {
    n = 0; first = 1
    while ((getline line < path) > 0) {
        # A UTF-8 byte order mark (Notepad, Windows PowerShell 5.1) would glue itself to
        # the first term and leave it unmatchable.
        if (first) { sub(/^\357\273\277/, "", line); first = 0 }
        sub(/\r$/, "", line)
        gsub(/^[ \t]+|[ \t]+$/, "", line)
        if (line == "" || line ~ /^#/) continue
        if (isterm && length(line) < minlen) continue
        arr[++n] = isterm ? tolower(line) : line
    }
    close(path)
    return n
}

function is_fixture(path) {
    return path ~ /(^|\/)([Tt]ests?|fixtures)\// || path ~ /(^|\/)test_[^\/]*$/
}

function allowed_path(candidate,    i) {
    for (i = 1; i <= nallow; i++) if (candidate ~ allow[i]) return 1
    return 0
}

# A URL scheme is the only look-alike of a drive path: a letter, a colon and TWO forward
# slashes right after another letter ("https://host", "file:///C:/x"). Only that shape is
# stepped over, and only by the letter and the colon, so a real path that follows it
# (file:///C:/Users/x) is still examined. A path after a literal "\n" or "\t" of a serialized
# log is not a scheme and is examined too.
function has_blocked_path(body,    rest, cand, prev) {
    rest = body; prev = ""
    while (match(rest, /[A-Za-z]:[\\\/]+[A-Za-z0-9_$%{.~][^ \t"'`<>|*?),;]*/)) {
        if (RSTART > 1) prev = substr(rest, RSTART - 1, 1)
        cand = substr(rest, RSTART, RLENGTH)
        if (prev ~ /[A-Za-z0-9]/ && cand ~ /^[A-Za-z]:\/\//) {
            rest = substr(rest, RSTART + 2); prev = ":"
            continue
        }
        rest = substr(rest, RSTART + RLENGTH)
        if (!allowed_path(cand)) return 1
        prev = substr(cand, length(cand), 1)
    }
    return 0
}

BEGIN {
    nterms = nallow = 0
    k = split(termfiles, tf, "|")
    for (i = 1; i <= k; i++) {
        delete part
        c = load_lines(tf[i], part, 1)
        for (j = 1; j <= c; j++) terms[++nterms] = part[j]
    }
    if (allowfile != "") nallow = load_lines(allowfile, allow, 0)
    msg = 0; hdr = 0; f = ""; pend = ""; pend_del = 0; csha = ""
}

/^commit [0-9a-f]+/ {
    flush_path()
    msg = 1; hdr = 0; csha = substr($2, 1, 12)
    f = "(commit message " csha ")"
    next
}
/^diff --git / {
    flush_path()
    msg = 0; hdr = 1
    i = 0; p = 0
    while ((p = index(substr($0, i + 1), " b/")) > 0) i += p
    f = (i > 0) ? substr($0, i + 3) : $0
    pend = f; pend_del = 0
    next
}
hdr && /^deleted file mode/ { pend_del = 1; next }
# The "diff --git" line is ambiguous for a directory named "x b" (" b/" splits it wrongly), so
# the exact path comes from "rename to", "copy to" or "+++" when the diff carries one of them.
hdr && /^(rename|copy) to / { f = substr($0, index($0, " to ") + 4); pend = f; next }
hdr && /^\+\+\+ / {
    if ($0 ~ /\/dev\/null/) pend_del = 1
    else { f = substr($0, 7); sub(/\t$/, "", f); pend = f }
    next
}
/^@@/ { flush_path(); hdr = 0; next }
hdr { next }
msg && /^(Author|Commit):/ {
    if (any_term($0)) emit("T", "(commit author " csha ")")
    next
}
msg && /^    / {
    if ($0 !~ /betterleaks:allow/ && any_term($0)) emit("T", "(commit message " csha ")")
    next
}
msg { next }
/^\+/ {
    if ($0 ~ /betterleaks:allow/) next
    body = substr($0, 2)
    if (any_term(body)) emit("T", f)
    if (pathmode != "off" && is_fixture(f) && has_blocked_path(body)) emit("P", f)
}
END { flush_path(); print "N\t" nterms }
