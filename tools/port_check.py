"""
port_check — 端口检测。
检测指定端口是否在监听，纯 socket 标准库。
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_MAX_SCAN_PORTS = 256  # 单次 scan 最多检测的端口数，超出截断


def check(host: str = "127.0.0.1", port: int = 7860) -> dict:
    """检测端口是否可连接。返回是否监听 + 连接延迟 latency_ms。"""
    sock = None
    start = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"ok": True, "host": host, "port": port, "listening": True, "latency_ms": latency_ms}
    except (socket.timeout, ConnectionRefusedError, OSError):
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "ok": True,
            "host": host,
            "port": port,
            "listening": False,
            "latency_ms": latency_ms,
            "proposal": f"端口 {port} 未监听",
            "evidence": {"host": host, "port": port, "timeout": 3},
            "options": [
                "确认服务是否已启动",
                "检查端口号是否正确",
                "端口未监听，可用 proc_list 按进程名查找服务进程",
            ],
        }
    finally:
        if sock:
            sock.close()


def scan(ports: list[int], host: str = "127.0.0.1") -> dict:
    """批量检测多个端口。返回每个端口的监听状态。超过 256 个端口时截断并附 note。"""
    note = ""
    if len(ports) > _MAX_SCAN_PORTS:
        note = f"端口数量 {len(ports)} 超过上限 {_MAX_SCAN_PORTS}，已截断为前 {_MAX_SCAN_PORTS} 个"
        ports = ports[:_MAX_SCAN_PORTS]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(32, len(ports)))) as executor:
        future_to_port = {executor.submit(check, host, port): port for port in ports}
        for future in as_completed(future_to_port):
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
        "results": results,
        "note": note,
    }
