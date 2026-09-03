"""
Phi 常驻守护进程客户端 (Client & Manager)
phi_client.py — Phase 6: 毫秒级任务分发

通过 172.31.1.1:19800 虚拟网络与卡内 phi_worker_daemon 通信，
消除 micnativeloadex 重复装载时延。
"""

import socket
import struct
import subprocess
import time
import os
from pathlib import Path
from typing import Optional, Tuple

WORK_ROOT = Path(__file__).resolve().parent.parent.parent
DAEMON_BIN = WORK_ROOT / "src" / "kernels" / "phi" / "phi_worker_daemon.mic"
MIC_LIBS = WORK_ROOT.parent / "intel_phi" / "icc_mic_libs"

MIC_IP = "172.31.1.1"
DEFAULT_PORT = 19800

MAGIC_REQ = 0x50484930   # "PHI0"
MAGIC_RESP = 0x50484931  # "PHI1"

OP_PING = 1
OP_FMA_PEAK = 2
OP_STATS = 3
OP_DATA_CLEAN = 4
OP_PATH_GEN = 5
OP_CSR_PARTITION = 6
OP_SHUTDOWN = 99

# Header: uint32 magic, opcode, payload_len, status, double gflops, elapsed_sec, char reserved[8]
HEADER_FMT = "<IIIIdd8s"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


class PhiDaemonManager:
    """管理 Phi 卡内常驻进程生命周期与任务通信"""

    def __init__(self, host: str = MIC_IP, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None

    def is_running(self) -> bool:
        """探测常驻进程是否正在监听"""
        try:
            with socket.create_connection((self.host, self.port), timeout=0.3):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def start_daemon(self, timeout_sec: float = 15.0, force: bool = False) -> bool:
        """通过 ssh 在 Phi 卡内后台启动常驻进程。

        force=True 时始终 scp 新二进制并 killall 后拉起，避免端口占用导致旧进程留存。
        """
        if self.is_running() and not force:
            return True
        if force:
            subprocess.run(
                "ssh mic0 'killall -9 phi_worker_daemon.mic 2>/dev/null; true'",
                shell=True, capture_output=True, timeout=10)
            time.sleep(0.4)

        # 确保二进制与必须的 Intel MIC 运行时动态库同步至 mic0:/tmp/
        libs = ["libiomp5.so", "libimf.so", "libsvml.so", "libintlc.so.5", "libirng.so"]
        scp_files = [str(DAEMON_BIN)]
        for lib in libs:
            lib_p = MIC_LIBS / lib
            if lib_p.exists():
                scp_files.append(str(lib_p))

        scp_cmd = f"scp {' '.join(scp_files)} mic0:/tmp/"
        subprocess.run(scp_cmd, shell=True, capture_output=True, timeout=30)

        # 同步启动脚本
        launcher_src = WORK_ROOT / "src" / "kernels" / "phi" / "run_daemon.sh"
        if launcher_src.exists():
            subprocess.run(f"scp {launcher_src} mic0:/tmp/run_daemon.sh && ssh mic0 'chmod +x /tmp/run_daemon.sh'", shell=True, capture_output=True)

        # 在卡内后台启动
        start_cmd = (
            f"ssh mic0 'nohup /tmp/run_daemon.sh > /dev/null 2>&1 < /dev/null &'"
        )
        subprocess.run(start_cmd, shell=True, capture_output=True, timeout=15)

        # 轮询探测可用性
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            if self.is_running():
                return True
            time.sleep(0.2)
        return False

    @staticmethod
    def _recv_exact(sock: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("connection closed while reading")
            buf.extend(chunk)
        return bytes(buf)

    def send_request(self, opcode: int, payload: bytes = b"") -> dict:
        """向常驻进程发送任务请求并返回结果"""
        if not self.is_running():
            if not self.start_daemon():
                return {"status": "fail", "error": "failed to start phi daemon"}

        try:
            with socket.create_connection((self.host, self.port), timeout=180.0) as s:
                header = struct.pack(
                    HEADER_FMT, MAGIC_REQ, opcode, len(payload), 0, 0.0, 0.0, b"\x00" * 8
                )
                t0 = time.time()
                s.sendall(header + payload)

                resp_hdr = self._recv_exact(s, HEADER_SIZE)
                magic, op, p_len, status, gflops, elapsed, _ = struct.unpack(HEADER_FMT, resp_hdr)
                extra = self._recv_exact(s, p_len) if p_len else b""
                net_elapsed = time.time() - t0

                if magic != MAGIC_RESP:
                    return {"status": "fail", "error": "invalid response magic"}

                return {
                    "status": "pass" if status == 1 else "fail",
                    "opcode": op,
                    "gflops": gflops,
                    "kernel_elapsed_sec": elapsed,
                    "total_roundtrip_sec": net_elapsed,
                    "payload": extra,
                }
        except Exception as e:
            return {"status": "fail", "error": str(e)}

    def ping(self) -> dict:
        return self.send_request(OP_PING)

    def run_fma_peak(self) -> dict:
        return self.send_request(OP_FMA_PEAK)

    def run_data_clean(self, blob: bytes) -> dict:
        """M×N 清洗：输入/输出均为 [int32 M][int32 N][float64 M*N]。"""
        res = self.send_request(OP_DATA_CLEAN, blob)
        if res.get("status") == "pass":
            res["cleaned"] = res.get("payload") or b""
        return res

    def run_path_gen(self, params: bytes) -> dict:
        """MC 路径：params 为 pack('ddddiid')；payload = valid,i32 + invalid,i32 + avgs。"""
        res = self.send_request(OP_PATH_GEN, params)
        extra = res.get("payload") or b""
        if res.get("status") == "pass" and len(extra) >= 8:
            valid, invalid = struct.unpack_from("<ii", extra)
            avgs = extra[8:]
            res.update({
                "valid": valid,
                "invalid": invalid,
                "paths_blob": struct.pack("<i", valid) + avgs,
                "stats_blob": struct.pack("<ii", valid, invalid),
            })
        return res

    def run_csr_partition(self, csr_blob: bytes) -> dict:
        """CSR 列三分块。返回 3 个与 csr_partition.c 相同的 block 二进制。"""
        res = self.send_request(OP_CSR_PARTITION, csr_blob)
        extra = res.get("payload") or b""
        blocks = []
        off = 0
        if res.get("status") == "pass":
            for _ in range(3):
                if off + 4 > len(extra):
                    res["status"] = "fail"
                    res["error"] = "truncated csr blocks"
                    break
                (nbytes,) = struct.unpack_from("<I", extra, off)
                off += 4
                blocks.append(extra[off:off + nbytes])
                off += nbytes
        res["blocks"] = blocks
        return res

    def run_stats(self, n: int, matrix: bytes) -> dict:
        """N×N float64 矩阵统计：min/max/mean/stddev。"""
        if n <= 0 or len(matrix) != n * n * 8:
            return {"status": "fail", "error": "matrix size mismatch"}
        payload = struct.pack("<i", n) + matrix
        res = self.send_request(OP_STATS, payload)
        extra = res.get("payload") or b""
        if res.get("status") == "pass" and len(extra) >= 32:
            mn, mx, mean, std = struct.unpack("<dddd", extra[:32])
            res.update({"min": mn, "max": mx, "mean": mean, "stddev": std})
        return res

    def shutdown(self) -> dict:
        res = self.send_request(OP_SHUTDOWN)
        time.sleep(0.2)
        return res
