"""
_http_utils — HTTP 安全校验共享代码。
供 http_get / http_download 内部使用，不作为独立工具暴露。
"""

import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse

_PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


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
    try:
        ip = ipaddress.ip_address(hostname)
        for net in _PRIVATE_NETS:
            if ip in net:
                return {"ok": False, "error": f"禁止访问内网地址: {hostname}"}
        # IPv4-mapped-IPv6: ::ffff:192.168.1.1 → 检查映射的 IPv4
        ipv4 = ip.ipv4_mapped
        if ipv4:
            for net in _PRIVATE_NETS:
                if ipv4 in net:
                    return {"ok": False, "error": f"禁止访问内网地址: {hostname}"}
    except (AttributeError, ValueError):
        pass
    try:
        addrs = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for addr in addrs:
            ip_str = addr[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
                for net in _PRIVATE_NETS:
                    if ip in net:
                        return {
                            "ok": False,
                            "error": f"禁止访问内网地址: {hostname} 解析到 {ip_str}",
                        }
            except ValueError:
                pass
    except socket.gaierror:
        pass
    return None


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """每次 HTTP 重定向前重新走 SSRF 校验，防止 302→127.0.0.1 绕过。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        err = validate_url(newurl)
        if err:
            raise urllib.error.URLError(f"重定向目标被拦截: {err['error']}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_opener():
    """创建带 SSRF 重定向校验的 URL opener。"""
    return urllib.request.build_opener(SafeRedirectHandler())


def check_url(url: str) -> dict | None:
    """SSRF 校验的便捷封装。"""
    return validate_url(url)
