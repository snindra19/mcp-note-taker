"""Check that a link is safe to fetch, so a note can't reach local services."""

import ipaddress
import socket
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2000
ALLOWED_SCHEMES = ("http", "https")

# IPv6 addresses in this range can carry an IPv4 address to a gateway.
NAT64_NETWORK = ipaddress.ip_network("64:ff9b::/96")

REFUSED_MESSAGE = "That address is not allowed. Links to local or private addresses are refused."


def is_public_ip(ip_text: str) -> bool:
    """Return True only for a public internet address."""
    # Windows can add a zone to IPv6 addresses, like fe80::1%3.
    ip_without_zone = ip_text.split("%")[0]
    try:
        address = ipaddress.ip_address(ip_without_zone)
    except ValueError:
        return False

    # An IPv6 address can wrap an IPv4 one, so check the wrapped address.
    if address.version == 6:
        if address in NAT64_NETWORK:
            return False
        wrapped_address = address.ipv4_mapped or address.sixtofour
        if wrapped_address is not None:
            address = wrapped_address

    # is_global excludes loopback, private, link-local and reserved addresses.
    return address.is_global and not address.is_multicast


def is_local_hostname(hostname: str) -> bool:
    """Return True for localhost, in any case, with or without a trailing dot."""
    name = hostname.lower().rstrip(".")
    return name == "localhost" or name.endswith(".localhost")


def resolve_hostname(hostname: str, port: int) -> list[str] | None:
    """Return every IP address for a hostname, or None if it can't be resolved."""
    try:
        results = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return None

    # Each result holds the address as the first item of its last field.
    addresses = []
    for result in results:
        addresses.append(result[4][0])
    return addresses


def check_link(url: str) -> str | None:
    """Return an error message if a URL must not be fetched, otherwise None."""
    if len(url) > MAX_URL_LENGTH:
        return f"The link must be at most {MAX_URL_LENGTH} characters."

    # URL parsers treat spaces, control characters and backslashes differently,
    # so refuse them instead of checking one host and fetching another.
    for character in url:
        if character <= " " or character == "\\":
            return "That is not a valid link."

    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return "That is not a valid link."

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        return "Only http and https links are allowed."
    if not hostname:
        return "That is not a valid link."
    if parts.username is not None or parts.password is not None:
        return "Links with a username or password are not allowed."
    if is_local_hostname(hostname):
        return REFUSED_MESSAGE

    if port is None:
        port = 443 if parts.scheme.lower() == "https" else 80
    addresses = resolve_hostname(hostname, port)
    if not addresses:
        return "Could not find that website. Check the link and try again."

    # One local address is enough to refuse, because any of them could be used.
    for address in addresses:
        if not is_public_ip(address):
            return REFUSED_MESSAGE
    return None
