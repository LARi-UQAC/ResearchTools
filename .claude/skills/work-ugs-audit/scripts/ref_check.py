"""
Reference check - form, reachability and citation of the references of one report.

Purpose: for every reference it reports the kind (standard, url or other), a status and whether the text of the
report cites it. A URL is only contacted at a public address that this module validated itself: the connection
goes to that address and never to the host name again, at every redirect hop.
Exit codes: 0 done, 2 refusal (missing file or missing configuration key).
"""
import argparse
import http
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse

import ugs_config

EXIT_REFUSAL = 2
CONFIG_KEYS = ("references.url_timeout_s", "references.max_retries", "references.max_redirects")
HTTP_SCHEMES = ("http", "https")
_NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")
_GLOBAL_UNICAST_V6 = ipaddress.ip_network("2000::/3")
_IPV4_MASK = int(ipaddress.IPv4Address("255.255.255.255"))


def _judged_address(ip: Any) -> Any:
    """
    Purpose: Replace an IPv6 address that embeds an IPv4 one by the IPv4 address it embeds.
    Details: The embedding forms are IPv4-mapped, 6to4 and NAT64 (64:ff9b::/96). Any other address is returned as is.
    Inputs:
        ip (IPv4Address | IPv6Address): the address to judge.
    Outputs:
        IPv4Address | IPv6Address: the address whose publicity decides.
    """
    if not isinstance(ip, ipaddress.IPv6Address):
        return ip
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64_NETWORK:
        return ipaddress.IPv4Address(int(ip) & _IPV4_MASK)
    return ip


def _is_public_address(address: str) -> bool:
    """
    Purpose: Tell whether one address string is a global, routable address.
    Details: Loopback, private, link-local, shared (carrier-grade NAT) and reserved ranges are not global, and an
        embedded IPv4 address is judged instead of its wrapper. A native IPv6 address must also sit in the global
        unicast block 2000::/3, which refuses the IPv4-compatible block ::/96 and the other translation prefixes
        (for example 64:ff9b:1::/48) that the standard library does not mark as non-global.
    Inputs:
        address (str): the address text.
    Outputs:
        bool: True when public. False when not, or when the text is not an address.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    judged = _judged_address(ip)
    if isinstance(judged, ipaddress.IPv6Address) and judged not in _GLOBAL_UNICAST_V6:
        return False
    return judged.is_global


def is_public_host(host: str, resolve: Callable[[str], list[str]]) -> bool:
    """
    Purpose: Tell whether a host name resolves to at least one public address.
    Inputs:
        host (str): the host name.
        resolve (Callable): host name to list of address strings.
    Outputs:
        bool: True when at least one address is public.
    """
    return any(_is_public_address(address) for address in resolve(host))


def classify(ref: str, patterns: list[dict]) -> str:
    """
    Purpose: Classify a reference as a standard, a url or something else.
    Inputs:
        ref (str): the reference text.
        patterns (list[dict]): standard patterns, each with a 'looks_like' key.
    Outputs:
        str: 'url' when the text holds a scheme and '://', 'standard' when a pattern looks like it, else 'other'.
    """
    if re.search(r"\w+://", ref):
        return "url"
    for pattern in patterns:
        looks_like = pattern.get("looks_like")
        if looks_like and re.search(looks_like, ref, re.IGNORECASE):
            return "standard"
    return "other"


def connect_validated(url: str, resolve: Callable[[str], list[str]], connect: Callable[..., Any], timeout: float) -> Any:
    """
    Purpose: Resolve the host of a URL once, take the first public address and connect to that address only.
    Inputs:
        url (str): the URL.
        resolve (Callable): host name to list of address strings.
        connect (Callable): (address, port, host, use_tls, timeout, target) to a status or a (status, location)
            pair. It receives the validated ADDRESS, the original host name (Host header and TLS server name) and the
            path with its query.
        timeout (float): connection timeout in seconds.
    Outputs:
        Any: what connect returns.
    Raises:
        ValueError: when the URL has no host, the host does not resolve, or no address is public.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError("No host in URL")
    use_tls = parsed.scheme == "https"
    port = parsed.port or (http.client.HTTPS_PORT if use_tls else http.client.HTTP_PORT)
    addresses = resolve(host)
    if not addresses:
        raise ValueError("Host did not resolve to any address")
    validated = next((address for address in addresses if _is_public_address(address)), None)
    if validated is None:
        raise ValueError("No validated public address found for host")
    target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    return connect(validated, port, host, use_tls, timeout, target)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """An HTTP connection that opens its socket to a given address and still names the original host."""

    def __init__(self, host: str, port: int, address: str, timeout: float) -> None:
        """
        Purpose: Remember the address to connect to.
        Inputs:
            host (str): host name, kept for the Host header.
            port (int): port.
            address (str): the validated address to connect to.
            timeout (float): connection timeout in seconds.
        Outputs:
            None.
        """
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        """
        Purpose: Open the socket to the pinned address, never to the host name.
        Inputs:
            None.
        Outputs:
            None. Sets self.sock.
        """
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """An HTTPS connection to a given address, with the original host name as TLS server name."""

    def __init__(self, host: str, port: int, address: str, timeout: float, context: ssl.SSLContext) -> None:
        """
        Purpose: Remember the address to connect to and the TLS context.
        Inputs:
            host (str): host name, used for the Host header, the SNI and the certificate check.
            port (int): port.
            address (str): the validated address to connect to.
            timeout (float): connection timeout in seconds.
            context (ssl.SSLContext): the TLS context.
        Outputs:
            None.
        """
        super().__init__(host, port, timeout=timeout, context=context)
        self._address = address
        self._tls_context = context

    def connect(self) -> None:
        """
        Purpose: Open the socket to the pinned address and wrap it in TLS for the original host name.
        Inputs:
            None.
        Outputs:
            None. Sets self.sock.
        """
        raw = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._tls_context.wrap_socket(raw, server_hostname=self.host)


def _request_pinned(address: str, port: int, host: str, use_tls: bool, timeout: float, target: str) -> Any:
    """
    Purpose: Send a HEAD request to a validated address and read the status line.
    Inputs:
        address (str): the validated address.
        port (int): port.
        host (str): original host name.
        use_tls (bool): True for https.
        timeout (float): timeout in seconds.
        target (str): path and query.
    Outputs:
        int | tuple: the status, or (status, location) when the response carries a Location header.
    Raises:
        OSError: on a connection, TLS or protocol failure (http.client errors are OSError or HTTPException).
    """
    if use_tls:
        conn = _PinnedHTTPSConnection(host, port, address, timeout, ssl.create_default_context())
    else:
        conn = _PinnedHTTPConnection(host, port, address, timeout)
    try:
        conn.request("HEAD", target)
        response = conn.getresponse()
        location = response.getheader("Location")
        return (response.status, location) if location else response.status
    except http.client.HTTPException as error:
        raise OSError(str(error)) from error
    finally:
        conn.close()


def _url_status(url: str, resolver: Callable, fetch: Callable, timeout: float, retries: int, max_redirects: int) -> str:
    """
    Purpose: Follow a URL through its redirects, validating every hop, and name the outcome.
    Inputs:
        url (str): the first URL (http or https).
        resolver (Callable): host name to list of address strings.
        fetch (Callable): the connector given to connect_validated.
        timeout (float): per-connection timeout in seconds.
        retries (int): extra attempts after a connection failure, counted over the whole chain.
        max_redirects (int): redirects followed before giving up.
    Outputs:
        str: 'reachable', 'blocked' (401 or 403), 'unreachable' or 'refused' (non-public host or non-http scheme).
    """
    current = url
    redirects = 0
    attempts = 0
    while True:
        try:
            result = connect_validated(current, resolver, fetch, timeout)
        except ValueError:
            return "refused"
        except OSError:
            attempts += 1
            if attempts > retries:
                return "unreachable"
            continue
        status, location = result if isinstance(result, tuple) else (result, None)
        if http.HTTPStatus.MULTIPLE_CHOICES <= status < http.HTTPStatus.BAD_REQUEST and location:
            redirects += 1
            if redirects > max_redirects:
                return "unreachable"
            current = urljoin(current, location)
            if urlparse(current).scheme not in HTTP_SCHEMES:
                return "refused"
            continue
        if http.HTTPStatus.OK <= status < http.HTTPStatus.MULTIPLE_CHOICES:
            return "reachable"
        if status in (http.HTTPStatus.UNAUTHORIZED, http.HTTPStatus.FORBIDDEN):
            return "blocked"
        return "unreachable"


def _standard_identifier(ref: str, patterns: list[dict]) -> Optional[str]:
    """
    Purpose: Find the text of the first standard pattern that matches a reference.
    Inputs:
        ref (str): the reference text.
        patterns (list[dict]): standard patterns, each with a 'regex' key.
    Outputs:
        str | None: the matched text, or None when no pattern matches.
    """
    for pattern in patterns:
        regex = pattern.get("regex")
        match = re.search(regex, ref, re.IGNORECASE) if regex else None
        if match:
            return match.group(0)
    return None


def check(ref: str, body_text: str, patterns: list[dict], fetch: Optional[Callable], timeout: float, retries: int,
          resolver: Optional[Callable[[str], list[str]]] = None, max_redirects: int = 0) -> dict:
    """
    Purpose: Check the form or reachability of one reference and whether the report cites it.
    Inputs:
        ref (str): the reference text.
        body_text (str): the text of the report.
        patterns (list[dict]): standard patterns ('looks_like' and 'regex').
        fetch (Callable | None): connector (address, port, host, use_tls, timeout, target) to a status or a
            (status, location) pair. None uses the real pinned HTTP connector.
        timeout (float): connection timeout in seconds.
        retries (int): extra attempts after a connection failure.
        resolver (Callable | None): host name to addresses. None means no URL can be validated, so a URL is refused.
        max_redirects (int): redirects followed.
    Outputs:
        dict: 'kind', 'status' and 'cited'. Status is form-ok or malformed for a standard, reachable, blocked,
            unreachable or refused for a URL, and not_checked otherwise.
    """
    kind = classify(ref, patterns)
    status = "not_checked"
    identifier = _standard_identifier(ref, patterns)
    if kind == "standard":
        status = "form-ok" if identifier else "malformed"
    elif kind == "url":
        url_match = re.search(r"\w+://\S+", ref)
        url = url_match.group(0) if url_match else ""
        scheme = urlparse(url).scheme
        if not url:
            status = "malformed"
        elif scheme not in HTTP_SCHEMES or resolver is None:
            status = "refused"
        else:
            status = _url_status(url, resolver, fetch or _request_pinned, timeout, retries, max_redirects)
    cited = (identifier in body_text) if (kind == "standard" and identifier) else (kind != "standard" and ref in body_text)
    return {"kind": kind, "status": status, "cited": cited}


def check_all(refs: list[str], body_text: str, patterns: list[dict], fetch: Optional[Callable], timeout: float,
              retries: int, resolver: Optional[Callable[[str], list[str]]] = None, max_redirects: int = 0) -> list[dict]:
    """
    Purpose: Check every reference of a report.
    Inputs:
        refs (list[str]): the references.
        body_text (str): the text of the report.
        patterns (list[dict]): standard patterns.
        fetch (Callable | None): connector, see check.
        timeout (float): connection timeout in seconds.
        retries (int): extra attempts after a connection failure.
        resolver (Callable | None): host name to addresses.
        max_redirects (int): redirects followed.
    Outputs:
        list[dict]: one result per reference, with a 1-based 'index'.
    """
    results = []
    for index, ref in enumerate(refs, start=1):
        result = check(ref, body_text, patterns, fetch, timeout, retries, resolver, max_redirects)
        result["index"] = index
        results.append(result)
    return results


def _default_resolver(host: str) -> list[str]:
    """
    Purpose: Resolve a host name with the system resolver.
    Inputs:
        host (str): the host name.
    Outputs:
        list[str]: the addresses, empty when the name does not resolve or is not a valid name.
    """
    try:
        return [info[4][0] for info in socket.getaddrinfo(host, None)]
    except (socket.gaierror, UnicodeError):
        return []


def _read_input(path_text: str, label: str) -> str:
    """
    Purpose: Read a text input or refuse the run.
    Inputs:
        path_text (str): the path.
        label (str): what the file is, for the message.
    Outputs:
        str: the file text.
    Raises:
        SystemExit: with code 2 when the file does not exist.
    """
    path = Path(path_text)
    if not path.exists():
        print(f"Error: {label} file not found: {path}", file=sys.stderr)
        sys.exit(EXIT_REFUSAL)
    return path.read_text(encoding="utf-8")


def main(argv: Optional[list[str]] = None) -> None:
    """
    Purpose: Command-line entry point: check the references of a report and print the results as JSON.
    Inputs:
        argv (list[str] | None): arguments, --refs FILE, --body FILE, optional --patterns FILE and --json.
    Outputs:
        None. Prints a JSON list on stdout.
    Raises:
        SystemExit: with code 2 when a file or a configuration key is missing.
    """
    parser = argparse.ArgumentParser(description="Check the references of a report.")
    parser.add_argument("--refs", required=True, help="File with one reference per line.")
    parser.add_argument("--body", required=True, help="File with the text of the report.")
    parser.add_argument("--patterns", help="File with the standard patterns (JSON).")
    parser.add_argument("--json", action="store_true", help="JSON output (the default).")
    args = parser.parse_args(argv)

    refs = [line.strip() for line in _read_input(args.refs, "refs").splitlines() if line.strip()]
    body_text = _read_input(args.body, "body")
    patterns = json.loads(_read_input(args.patterns, "patterns")) if args.patterns else []

    try:
        config = ugs_config.load(ugs_config.default_path())
    except ugs_config.ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(EXIT_REFUSAL)
    for key in CONFIG_KEYS:
        if key not in config:
            print(f"Error: missing configuration key '{key}'", file=sys.stderr)
            sys.exit(EXIT_REFUSAL)
    results = check_all(refs, body_text, patterns, None, config["references.url_timeout_s"],
                        config["references.max_retries"], _default_resolver, config["references.max_redirects"])
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
