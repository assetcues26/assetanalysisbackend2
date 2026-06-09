"""Local network helpers for LAN API access."""

import socket


def _is_usable_lan(ip: str) -> bool:
    if not ip or ip.startswith("127."):
        return False
    if ip.startswith("169.254."):
        return False
    return True


def get_lan_ipv4() -> str | None:
    """Primary LAN IPv4 used for outbound traffic (usually Wi‑Fi)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if _is_usable_lan(ip):
                return ip
    except OSError:
        pass
    return None


def get_all_lan_ipv4() -> list[str]:
    """Known LAN addresses (primary first)."""
    primary = get_lan_ipv4()
    return [primary] if primary else []
