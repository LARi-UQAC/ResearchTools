"""
reviewer_schema.py - canonical reviewer-schema expansion shared by both panel legs.

The deliberation panel asks the models for a short-key, coded-enum schema because the keys
repeat once per suggestion and the saving is real. Every response, coded or not, is routed
back through expand_schema() before it reaches the merge logic, so the protocol markers and
the rest of the pipeline only ever see canonical keys.

This lives in the scopus scripts folder, next to gemini_reviewer.py and github_reviewer.py,
because both reviewer cores need it and deliberate.py imports the cores from here. Putting
it in deliberate.py instead would make the reviewers import their own caller.
"""

# coded-key -> canonical-key (applied to dict keys at any level; canonical keys pass through)
KEY_FROM_CODE = {
    "a": "overall_assessment", "x": "suggestions", "s": "target_section", "t": "type",
    "m": "suggestion", "c": "confidence", "v": "requires_scopus_validation",
    "r": "responses_to_other", "st": "stance", "rs": "reason",
}
# coded-value -> canonical-value, applied only to the named fields after key expansion
TYPE_FROM_CODE = {"ti": "text_improvement", "ri": "reference_issue", "cg": "coverage_gap",
                  "sy": "style", "sc": "structure"}
CONF_FROM_CODE = {"h": "high", "m": "medium", "l": "low"}
STANCE_FROM_CODE = {"a": "agree", "d": "disagree", "p": "partial"}


def expand_schema(obj):
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a coded-key model response back to the canonical reviewer schema so
        the merge/arbitration logic is unchanged. Idempotent and safe on already-
        canonical input (the standalone CLIs and the offline test fixtures emit
        full keys), so it can run unconditionally after every model call.

    Inputs:
        obj (dict | list | scalar): a parsed model response (coded or canonical).

    Outputs:
        expanded (same shape): canonical keys and enum values.
    --------------------------------------------------------------------------
    """
    if isinstance(obj, list):
        return [expand_schema(i) for i in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        out[KEY_FROM_CODE.get(k, k)] = expand_schema(v) if isinstance(v, (dict, list)) else v
    if isinstance(out.get("type"), str):
        out["type"] = TYPE_FROM_CODE.get(out["type"], out["type"])
    if isinstance(out.get("confidence"), str):
        out["confidence"] = CONF_FROM_CODE.get(out["confidence"], out["confidence"])
    if isinstance(out.get("stance"), str):
        out["stance"] = STANCE_FROM_CODE.get(out["stance"], out["stance"])
    return out


def error_object(message: str, raw: str = "") -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the schema-shaped object a leg returns when its response could not
        be parsed. Keeping the truncated raw text under `_raw` means a panel that
        loses a critique says so, instead of reporting an empty review that looks
        like agreement.

    Inputs:
        message (str): the failure description.
        raw (str): the model's unparsable text, truncated by the caller's budget.

    Outputs:
        obj (dict): canonical-shaped object carrying `_error` and, when known, `_raw`.
    --------------------------------------------------------------------------
    """
    obj = {"overall_assessment": "", "suggestions": [], "_error": message}
    if raw:
        obj["_raw"] = raw[:500]
    return obj
