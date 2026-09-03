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
OP_SHUTDOWN = 99

# Header: uint32 magic, uint32 opcode, uint32 payload_len, uint32 status, double gflops, double elapsed_sec, char reserved[8]
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

    def start_daemon(self, timeout_sec: float = 15.0) -> bool:
        """通过 ssh 在 Phi 卡内后台启动常驻进程"""
        if self.is_running():
            return True

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

    def send_request(self, opcode: int, payload: bytes = b"") -> dict:
        """向常驻进程发送任务请求并返回结果"""
        if not self.is_running():
            if not self.start_daemon():
                return {"status": "fail", "error": "failed to start phi daemon"}

        try:
            with socket.create_connection((self.host, self.port), timeout=60.0) as s:
                # 打包请求头
                header = struct.pack(HEADER_FMT, MAGIC_REQ, opcode, len(payload), 0, 0.0, 0.0, b"\x00"*8)
                t0 = time.time()
                s.sendall(header + payload)

                # 接收响应头
                resp_hdr = s.recv(HEADER_SIZE)
                if len(resp_hdr) < HEADER_SIZE:
                    return {"status": "fail", "error": "incomplete response header"}

                magic, op, p_len, status, gflops, elapsed, _ = struct.unpack(HEADER_FMT, resp_hdr)
                net_elapsed = time.time() - t0

                if magic != MAGIC_RESP:
                    return {"status": "fail", "error": "invalid response magic"}

                return {
                    "status": "pass" if status == 1 else "fail",
                    "opcode": op,
                    "gflops": gflops,
                    "kernel_elapsed_sec": elapsed,
                    "total_roundtrip_sec": net_elapsed,
                }
        except Exception as e:
            return {"status": "fail", "error": str(e)}

    def ping(self) -> dict:
        return self.send_request(OP_PING)

    def run_fma_peak(self) -> dict:
        return self.send_request(OP_FMA_PEAK)

    def shutdown(self) -> dict:
        res = self.send_request(OP_SHUTDOWN)
        time.sleep(0.2)
        return res
