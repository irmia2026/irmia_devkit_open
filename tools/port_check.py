"""
port_check — 端口检测。
检测指定端口是否在监听，纯 socket 标准库。
"""

import socket




def check(host: str = "127.0.0.1", port: int = 7860) -> dict:
    """检测端口是否可连接。返回是否监听 + 延迟。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        return {"ok": True, "host": host, "port": port, "listening": True}
    except (socket.timeout, ConnectionRefusedError, OSError):
        return {
            "ok": True,
            "host": host,
            "port": port,
            "listening": False,
            "proposal": f"端口 {port} 未监听",
            "evidence": {"host": host, "port": port, "timeout": 3},
            "options": ["确认服务是否已启动", "检查端口号是否正确", "用 proc_list 确认进程"],
            "next_call": {"tool": "proc_list", "params": {"filter_name": str(port)}},
        }
    finally:
        if sock:
            sock.close()


def scan(ports: list[int], host: str = "127.0.0.1") -> dict:
    """批量检测多个端口。返回每个端口的监听状态。"""
    results = []
    for port in ports:
        r = check(host, port)
        results.append({"port": port, "listening": r["listening"]})

    return {
        "ok": True,
        "host": host,
        "listening": [r["port"] for r in results if r["listening"]],
        "closed": [r["port"] for r in results if not r["listening"]],
        "results": results,
    }
