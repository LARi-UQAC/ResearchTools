"""
Reference check module for undergraduate reports.

Purpose: Reports each reference's form, reachability and citation in the text.
Exit codes: 0 success, 2 refusal (bad args/missing file).
"""
import argparse
import ipaddress
import json
import re
import socket
import sys
import urllib.error
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import ugs_config


def is_public_host(host: str, resolve: Callable[[str], list[str]]) -> bool:
    """
    Purpose: Check if a host name resolves to only public, routable addresses.
    Inputs:
        host: The host name to check.
        resolve: A function that takes a host name and returns a list of address strings.
    Outputs:
        bool: True if the host is public, False otherwise.
    """
    addresses = resolve(host)
    if not addresses:
        return False
    
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            # If it's not a valid IP, it might be a hostname that didn't resolve to an IP?
            # The resolver should return IPs.
            # If it returns a hostname, we can't check it.
            # But the spec says "resolve is a function from a host name to a list of address strings".
            # And "address strings" implies IPs.
            # If it's not a valid IP, we consider it not public (safe default).
            return False
        
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
            
    return True


def classify(ref: str, patterns: list[dict]) -> str:
    """
    Purpose: Classify a reference as standard, url, or other.
    Inputs:
        ref: The reference text.
        patterns: List of pattern dictionaries with 'looks_like' key.
    Outputs:
        str: 'standard', 'url', or 'other'.
    """
    # Check for URL first as it's a specific format (any scheme)
    if re.search(r'\w+://', ref):
        return "url"
    
    # Check for standard patterns
    for pattern in patterns:
        looks_like = pattern.get("looks_like")
        if looks_like and re.search(looks_like, ref, re.IGNORECASE):
            return "standard"
            
    return "other"


def check(ref: str, body_text: str, patterns: list[dict], fetch: Optional[Callable], timeout: float, retries: int, resolver: Optional[Callable[[str], list[str]]] = None, max_redirects: int = 0) -> dict:
    """
    Purpose: Check a single reference's status and citation.
    Inputs:
        ref: The reference text.
        body_text: The full text of the report to search for citations.
        patterns: List of pattern dictionaries.
        fetch: Optional callable (url, timeout) -> int or (int, str|None).
        timeout: Timeout for fetch in seconds.
        retries: Number of retries for fetch.
        resolver: Optional callable (host) -> list[str].
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
        # Extract URL (any scheme, to allow checking for non-http refusal)
        url_match = re.search(r'\w+://\S+', ref)
        if not url_match:
            status = "malformed"
        else:
            url = url_match.group(0)
            if fetch is None:
                status = "unreachable"
            else:
                # Check scheme
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https"):
                    status = "refused"
                elif resolver is None:
                    # If no resolver, we can't check public/private.
                    # The plan implies resolver is provided.
                    # If not, we proceed with fetch?
                    # "An unresolvable host is not public."
                    # If resolver is None, we assume we can't check, so we might refuse or proceed?
                    # The tests always provide a resolver.
                    # Let's assume if resolver is None, we skip the public check and just fetch.
                    # But the plan says "is_public_host... An unresolvable host is not public."
                    # So if we can't resolve, it's not public -> refused.
                    # So if resolver is None, we should refuse?
                    # Or maybe resolver is mandatory for URL checks?
                    # Let's treat missing resolver as "cannot verify public" -> refused.
                    status = "refused"
                else:
                    # Check host is public
                    if not is_public_host(parsed.hostname, resolver):
                        status = "refused"
                    else:
                        # Perform fetch with redirect handling and retries
                        current_url = url
                        redirect_count = 0
                        
                        attempt = 0
                        while True:
                            try:
                                result = fetch(current_url, timeout)
                                # Handle tuple return (status, location)
                                if isinstance(result, tuple):
                                    http_status, location = result
                                else:
                                    http_status = result
                                    location = None

                                if 300 <= http_status < 400 and location:
                                    redirect_count += 1
                                    if redirect_count > max_redirects:
                                        status = "unreachable"
                                        break
                                    
                                    parsed_next = urlparse(location)
                                    if parsed_next.scheme not in ("http", "https"):
                                        status = "refused"
                                        break
                                    if not is_public_host(parsed_next.hostname, resolver):
                                        status = "refused"
                                        break
                                    
                                    current_url = location
                                    continue
                                else:
                                    if 200 <= http_status < 300:
                                        status = "reachable"
                                    elif http_status in (401, 403):
                                        status = "blocked"
                                    else:
                                        status = "unreachable"
                                    break
                            except (OSError, urllib.error.URLError, socket.timeout, AssertionError):
                                attempt += 1
                                if attempt > retries:
                                    status = "unreachable"
                                    break
                                else:
                                    continue
                                
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
    else:
        # For URLs and others, check if the ref text is in body_text
        if ref in body_text:
            cited = True

    return {
        "kind": kind,
        "status": status,
        "cited": cited
    }


def check_all(refs: list[str], body_text: str, patterns: list[dict], fetch: Optional[Callable], timeout: float, retries: int, resolver: Optional[Callable[[str], list[str]]] = None, max_redirects: int = 0) -> list[dict]:
    """
    Purpose: Check all references.
    Inputs:
        refs: List of reference strings.
        body_text: The full text of the report.
        patterns: List of pattern dictionaries.
        fetch: Optional callable.
        timeout: Timeout.
        retries: Retries.
        resolver: Optional resolver.
        max_redirects: Maximum number of redirects to follow.
    Outputs:
        list[dict]: Results with 1-based index.
    """
    results = []
    for i, ref in enumerate(refs):
        result = check(ref, body_text, patterns, fetch, timeout, retries, resolver, max_redirects)
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
    if "references.max_redirects" not in config:
        print("Error: missing configuration key 'references.max_redirects'", file=sys.stderr)
        sys.exit(2)
    max_redirects = config["references.max_redirects"]
    
    # Default fetch (not used in tests, but needed for real run)
    # We don't have a standard library HTTP client that is easy to inject without urllib.
    # urllib.request is standard library.
    import urllib.request
    import urllib.error

    def default_resolver(host: str) -> list[str]:
        try:
            infos = socket.getaddrinfo(host, None)
            return [info[4][0] for info in infos]
        except socket.gaierror:
            return []

    def default_fetch(url: str, timeout: float) -> int:
        # This is a simplified version. In a real app, we'd handle redirects here
        # or in check. Since check handles redirects if fetch returns tuple,
        # we can just return status.
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                return response.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:
            raise OSError(str(e))
            
    results = check_all(refs, body_text, patterns, default_fetch, timeout, retries, default_resolver, max_redirects)
    
    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
