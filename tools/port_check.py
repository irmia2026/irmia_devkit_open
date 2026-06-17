"""
port_check — 端口检测。
检测指定端口是否在监听，纯 socket 标准库。
"""

import socket
import concurrent.futures


def check(host: str = "127.0.0.1", port: int = 7860) -> dict:
    """检测端口是否可连接。返回是否监听 + 延迟。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)  # 1秒超时，避免长时间阻塞
        sock.connect((host, port))
        return {"ok": True, "host": host, "port": port, "listening": True}
    except (socket.timeout, ConnectionRefusedError, OSError):
        return {
            "ok": True,
            "host": host,
            "port": port,
            "listening": False,
            "proposal": f"端口 {port} 未监听",
            "evidence": {"host": host, "port": port, "timeout": 1},
            "options": ["确认服务是否已启动", "检查端口号是否正确", "用 proc_list 确认进程"],
            "next_call": {"tool": "proc_list", "params": {"filter_name": str(port)}},
        }
    finally:
        if sock:
            sock.close()


def scan(ports: list[int], host: str = "127.0.0.1") -> dict:
    """批量检测多个端口。并发扫描，返回每个端口的监听状态。"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(32, len(ports))) as pool:
        future_to_port = {pool.submit(check, host, port): port for port in ports}
        for future in concurrent.futures.as_completed(future_to_port):
            port = future_to_port[future]
            try:
                r = future.result()
                results.append({"port": port, "listening": r["listening"]})
            except Exception:
                results.append({"port": port, "listening": False})

    return {
        "ok": True,
        "host": host,
        "listening": [r["port"] for r in results if r["listening"]],
        "closed": [r["port"] for r in results if not r["listening"]],
        "results": sorted(results, key=lambda x: x["port"]),
    }
