"""Tests for port_check."""

import socket
import threading

from tools import port_check as pc


class TestCheck:
    def test_returns_dict(self):
        r = pc.check("127.0.0.1", 0)
        assert isinstance(r, dict)
        assert "listening" in r
        assert r["listening"] in (True, False)

    def test_listening_true_with_temp_server(self):
        host = "127.0.0.1"
        # Bind to port 0 to get a free port.
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, 0))
        port = server.getsockname()[1]
        server.listen(1)
        stop = threading.Event()

        def accept_once():
            server.settimeout(1.0)
            try:
                conn, _ = server.accept()
                conn.close()
            except socket.timeout:
                pass
            stop.set()

        t = threading.Thread(target=accept_once, daemon=True)
        t.start()
        try:
            r = pc.check(host, port)
            assert r["ok"] is True
            assert r["listening"] is True
            assert r["host"] == host
            assert r["port"] == port
            assert isinstance(r["latency_ms"], (int, float))
            assert r["latency_ms"] >= 0
        finally:
            stop.wait(timeout=2)
            server.close()

    def test_listening_false(self):
        # High port unlikely to be used.
        r = pc.check("127.0.0.1", 1)
        assert r["ok"] is True
        assert r["listening"] is False
        assert "proposal" in r
        assert "latency_ms" in r
        # next_call 已移除，改为 options 文案提示 proc_list
        assert "next_call" not in r
        assert any("proc_list" in o for o in r["options"])


class TestScan:
    def test_empty_ports(self):
        r = pc.scan([])
        assert r["ok"] is True
        assert r["listening"] == []
        assert r["closed"] == []
        assert r["results"] == []

    def test_scan_closed_ports(self):
        r = pc.scan([1, 2], host="127.0.0.1")
        assert r["ok"] is True
        assert sorted(r["closed"]) == [1, 2]
        assert r["listening"] == []
        assert len(r["results"]) == 2

    def test_scan_with_listening_port(self):
        host = "127.0.0.1"
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, 0))
        port = server.getsockname()[1]
        server.listen(1)
        stop = threading.Event()

        def accept_once():
            server.settimeout(1.0)
            try:
                conn, _ = server.accept()
                conn.close()
            except socket.timeout:
                pass
            stop.set()

        t = threading.Thread(target=accept_once, daemon=True)
        t.start()
        try:
            r = pc.scan([port, 1], host=host)
            assert r["ok"] is True
            assert port in r["listening"]
            assert 1 in r["closed"]
        finally:
            stop.wait(timeout=2)
            server.close()

    def test_scan_returns_port_results(self):
        r = pc.scan([1])
        assert r["results"][0]["port"] == 1
        assert r["results"][0]["listening"] is False
        assert r["note"] == ""

    def test_scan_truncates_over_256_ports(self):
        ports = list(range(1, 300))  # 299 个端口
        r = pc.scan(ports, host="127.0.0.1")
        assert r["ok"] is True
        assert len(r["results"]) == 256
        assert "截断" in r["note"]
