"""
Reference check module for undergraduate reports.

Purpose: Reports each reference's form, reachability and citation in the text.
Exit codes: 0 success, 2 refusal (bad args/missing file).
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import ugs_config


def classify(ref: str, patterns: list[dict]) -> str:
    """
    Purpose: Classify a reference as standard, url, or other.
    Inputs:
        ref: The reference text.
        patterns: List of pattern dictionaries with 'looks_like' key.
    Outputs:
        str: 'standard', 'url', or 'other'.
    """
    # Check for URL first as it's a specific format
    if re.search(r'https?://', ref):
        return "url"
    
    # Check for standard patterns
    for pattern in patterns:
        looks_like = pattern.get("looks_like")
        if looks_like and re.search(looks_like, ref, re.IGNORECASE):
            return "standard"
            
    return "other"


def check(ref: str, body_text: str, patterns: list[dict], fetch: Optional[Callable], timeout: float, retries: int) -> dict:
    """
    Purpose: Check a single reference's status and citation.
    Inputs:
        ref: The reference text.
        body_text: The full text of the report to search for citations.
        patterns: List of pattern dictionaries.
        fetch: Optional callable (url, timeout) -> int.
        timeout: Timeout for fetch in seconds.
        retries: Number of retries for fetch.
    Outputs:
        dict: With keys 'kind', 'status', 'cited'.
    """
    kind = classify(ref, patterns)
    status = "not_checked"
    
    if kind == "standard":
        # Check form against regex
        is_form_ok = False
        for pattern in patterns:
            regex = pattern.get("regex")
            if regex and re.search(regex, ref, re.IGNORECASE):
                is_form_ok = True
                break
        status = "form-ok" if is_form_ok else "malformed"
        
    elif kind == "url":
        # Extract URL
        url_match = re.search(r'https?://\S+', ref)
        if not url_match:
            status = "malformed"
        else:
            url = url_match.group(0)
            if fetch is None:
                status = "unreachable"
            else:
                for _ in range(retries + 1):
                    try:
                        http_status = fetch(url, timeout)
                        if 200 <= http_status <= 399:
                            status = "reachable"
                        elif http_status in (401, 403):
                            status = "blocked"
                        else:
                            status = "unreachable"
                        break
                    except Exception:
                        continue
                else:
                    status = "unreachable"
                    
    # Check citation
    cited = False
    if kind == "standard":
        # For standards, check if the identifier (regex match) is in body_text
        identifier = None
        for pattern in patterns:
            regex = pattern.get("regex")
            if regex:
                match = re.search(regex, ref, re.IGNORECASE)
                if match:
                    identifier = match.group(0)
                    break
        if identifier and identifier in body_text:
            cited = True
        elif ref in body_text:
            cited = True
    else:
        # For URLs and others, check if the ref text is in body_text
        if ref in body_text:
            cited = True

    return {
        "kind": kind,
        "status": status,
        "cited": cited
    }


def check_all(refs: list[str], body_text: str, patterns: list[dict], fetch: Optional[Callable], timeout: float, retries: int) -> list[dict]:
    """
    Purpose: Check all references.
    Inputs:
        refs: List of reference strings.
        body_text: The full text of the report.
        patterns: List of pattern dictionaries.
        fetch: Optional callable.
        timeout: Timeout.
        retries: Retries.
    Outputs:
        list[dict]: Results with 1-based index.
    """
    results = []
    for i, ref in enumerate(refs):
        result = check(ref, body_text, patterns, fetch, timeout, retries)
        result["index"] = i + 1
        results.append(result)
    return results


def main(argv: Optional[list[str]] = None) -> None:
    """
    Purpose: Main entry point for the reference check script.
    Inputs:
        argv: Command line arguments.
    Outputs:
        None. Prints JSON to stdout.
    Raises:
        SystemExit: With code 0 or 2.
    """
    parser = argparse.ArgumentParser(description="Check references in a report.")
    parser.add_argument("--refs", required=True, help="File with one reference per line.")
    parser.add_argument("--body", required=True, help="File with the report body text.")
    parser.add_argument("--patterns", help="File with standard patterns (JSON).")
    parser.add_argument("--json", action="store_true", help="Output as JSON (default).")
    
    args = parser.parse_args(argv)
    
    # Load refs
    refs_path = Path(args.refs)
    if not refs_path.exists():
        print(f"Error: refs file not found: {refs_path}", file=sys.stderr)
        sys.exit(2)
        
    refs = [line.strip() for line in refs_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    
    # Load body
    body_path = Path(args.body)
    if not body_path.exists():
        print(f"Error: body file not found: {body_path}", file=sys.stderr)
        sys.exit(2)
        
    body_text = body_path.read_text(encoding='utf-8')
    
    # Load patterns
    patterns = []
    if args.patterns:
        patterns_path = Path(args.patterns)
        if not patterns_path.exists():
            print(f"Error: patterns file not found: {patterns_path}", file=sys.stderr)
            sys.exit(2)
        patterns = json.loads(patterns_path.read_text(encoding='utf-8'))
        
    # Load config for timeout and retries
    config = ugs_config.load()
    if "references.url_timeout_s" not in config:
        print("Error: missing configuration key 'references.url_timeout_s'", file=sys.stderr)
        sys.exit(2)
    if "references.max_retries" not in config:
        print("Error: missing configuration key 'references.max_retries'", file=sys.stderr)
        sys.exit(2)
        
    timeout = config["references.url_timeout_s"]
    retries = config["references.max_retries"]
    
    # Default fetch (not used in tests, but needed for real run)
    # We don't have a standard library HTTP client that is easy to inject without urllib.
    # urllib.request is standard library.
    import urllib.request
    
    def default_fetch(url: str, timeout: float) -> int:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:
            raise OSError(str(e))
            
    results = check_all(refs, body_text, patterns, default_fetch, timeout, retries)
    
    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
