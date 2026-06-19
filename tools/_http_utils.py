"""
_http_utils — HTTP 安全校验共享代码。
供 http_get / http_download 内部使用，不作为独立工具暴露。
"""

import ipaddress
import socket
from urllib.parse import urlparse

# 预编译的私有网络集合——避免每次调用重新构建
_PRIVATE_NETS = frozenset([
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
])


# 延迟初始化：首次调用时构建 opener
_SAFE_OPENER = None


def _build_opener():
    """构建带 SSRF 重定向校验的 URL opener（延迟初始化）。"""
    import urllib.request
    import urllib.error

    class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        """每次 HTTP 重定向前重新走 SSRF 校验，防止 302→127.0.0.1 绕过。"""

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            err = validate_url(newurl)
            if err:
                raise urllib.error.URLError(f"重定向目标被拦截: {err['error']}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return urllib.request.build_opener(SafeRedirectHandler())


def make_opener():
    """创建带 SSRF 重定向校验的 URL opener（单例）。"""
    global _SAFE_OPENER
    if _SAFE_OPENER is None:
        _SAFE_OPENER = _build_opener()
    return _SAFE_OPENER


def _is_private_ip(host: str) -> str | None:
    """判断 host 是否为内网/本地 IP。

    先用 socket.inet_aton 标准化 IPv4 的各种写法（八进制、十六进制、短写法），
    再用 ipaddress 判断是否属于私有网络。对 IPv6 字面量同样处理。
    """
    # 1) IPv4 任意进制 / 缩写标准化：0177.0.0.1 / 0x7f.0.0.1 / 127.1 等
    try:
        normalized = socket.inet_ntoa(socket.inet_aton(host))
        ip = ipaddress.ip_address(normalized)
        for net in _PRIVATE_NETS:
            if ip in net:
                return f"禁止访问内网地址: {host}"
    except (OSError, ValueError):
        pass

    # 2) IPv6 字面量（含 IPv4-mapped）
    try:
        ip = ipaddress.ip_address(host)
        for net in _PRIVATE_NETS:
            if ip in net:
                return f"禁止访问内网地址: {host}"
        if isinstance(ip, ipaddress.IPv6Address):
            ipv4 = ip.ipv4_mapped
            if ipv4:
                for net in _PRIVATE_NETS:
                    if ipv4 in net:
                        return f"禁止访问内网地址: {host}"
    except ValueError:
        pass

    return None


def validate_url(url: str) -> dict | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {
            "ok": False,
            "error": f"不支持的协议: {parsed.scheme}，仅允许 http/https",
        }
    hostname = parsed.hostname
    if not hostname:
        return {"ok": False, "error": "URL 缺少有效主机名"}

    err = _is_private_ip(hostname)
    if err:
        return {"ok": False, "error": err}

    try:
        addrs = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for addr in addrs:
            ip_str = addr[4][0]
            err2 = _is_private_ip(ip_str)
            if err2:
                return {
                    "ok": False,
                    "error": f"{hostname} 解析到内网地址 {ip_str}",
                }
    except socket.gaierror:
        pass
    return None


def check_url(url: str) -> dict | None:
    """SSRF 校验的便捷封装。"""
    return validate_url(url)
