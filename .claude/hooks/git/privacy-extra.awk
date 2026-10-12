# Privacy guard, extra scan - installed by install-git-hooks.ps1, read by privacy-lib.sh.
#
# Purpose: two checks no betterleaks rule can make.
#   T  a term of the machine-local deny list (real student names, data folders) in an
#      added line, a changed file path or a commit message. The list is never committed:
#      publishing it would be the leak it prevents.
#   P  an absolute drive path in an added line of a test or fixture file, the way a real
#      run's output reaches a fixture (measured 2026-10-12, ResearchTools PR #69).
# Input (stdin): diff text, as `git diff --cached -U0` or `git log -p -m -U0
#   --pretty=medium` print it. Output: one "<kind><TAB><file>" line per finding, never
#   the matched line or term. Exit 0 always; the caller decides what a finding means.
# Variables (-v): termfiles ("|"-separated deny-list files), minlen (shortest term kept),
#   pathmode (off | warn | refuse, "off" skips check P), allowfile (regexes, one per line,
#   an absolute path matching one is not reported).
# A line carrying "betterleaks:allow" is skipped, like every other privacy check.

function token_hit(line, name,    l, n, s, p, pos, before, after) {
    l = tolower(line); n = length(name); s = 1
    while ((p = index(substr(l, s), name)) > 0) {
        pos = s + p - 1
        before = (pos > 1) ? substr(l, pos - 1, 1) : ""
        after = substr(l, pos + n, 1)
        if (before !~ /[a-z0-9_]/ && after !~ /[a-z0-9_]/) return 1
        s = pos + 1
    }
    return 0
}

function any_term(text,    i) {
    for (i = 1; i <= nterms; i++) if (token_hit(text, terms[i])) return 1
    return 0
}

function emit(kind, where,    key) {
    key = kind "\t" where
    if (!(key in seen)) { seen[key] = 1; print key }
}

function load_lines(path, arr, isterm,    line, n) {
    n = 0
    while ((getline line < path) > 0) {
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

function has_blocked_path(body,    rest, cand) {
    rest = body
    while (match(rest, /[A-Za-z]:[\\\/]+[A-Za-z0-9_$%{.~][^ \t"'`<>|*?),;]*/)) {
        cand = substr(rest, RSTART, RLENGTH)
        if (!allowed_path(cand)) return 1
        rest = substr(rest, RSTART + RLENGTH)
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
    msg = 0; hdr = 0; f = ""
}

/^commit [0-9a-f]+/ { msg = 1; hdr = 0; f = "(commit message " substr($2, 1, 12) ")"; next }
/^diff --git / {
    msg = 0; hdr = 1
    i = 0; p = 0
    while ((p = index(substr($0, i + 1), " b/")) > 0) i += p
    f = (i > 0) ? substr($0, i + 3) : $0
    if (any_term(f)) emit("T", f)
    next
}
hdr && /^\+\+\+ / { if ($0 !~ /\/dev\/null/) f = substr($0, 7); next }
/^@@/ { hdr = 0; next }
hdr { next }
msg && /^    / {
    if ($0 !~ /betterleaks:allow/ && any_term($0)) emit("T", f)
    next
}
msg { next }
/^\+/ {
    if ($0 ~ /betterleaks:allow/) next
    body = substr($0, 2)
    if (any_term(body)) emit("T", f)
    if (pathmode != "off" && is_fixture(f) && has_blocked_path(body)) emit("P", f)
}
