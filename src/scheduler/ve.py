"""
调度层 — NEC VE 1.0 管理
ve.py — 编译 (ncc) + 部署 + 执行 + 结果解析
"""

import subprocess
import os
from pathlib import Path

WORK_ROOT = Path(__file__).resolve().parent.parent.parent  # uni/
VE_KERNEL_SRC = WORK_ROOT / "src" / "kernels" / "ve" / "peak_fp64.c"
VE_DGEMM_SRC = WORK_ROOT / "src" / "kernels" / "ve" / "dgemm_nlc.c"
VE_DGEMM_BIN = WORK_ROOT / "src" / "kernels" / "ve" / "dgemm_nlc_ve"
NLC_DIR = Path("/opt/nec/ve/nlc/3.1.0")


def compile_ve_kernel() -> bool:
    """使用 ncc 编译 VE 基础 FMA 内核"""
    src = VE_KERNEL_SRC
    if not src.exists():
        print(f"[ve] 内核源码不存在: {src}")
        return False

    print("[ve] 编译内核 (ncc -fopenmp)...")
    cmd = f"ncc -O3 -fopenmp -o {VE_KERNEL_BIN} {src}"

    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=60
    )

    if result.returncode != 0:
        print(f"[ve] 编译失败:\n{result.stderr}")
        return False

    print(f"[ve] 编译成功 → {VE_KERNEL_BIN}")
    return True


def compile_ve_dgemm_nlc() -> bool:
    """使用 ncc 链接 NEC NLC 数学库编译 DGEMM 内核"""
    if VE_DGEMM_BIN.exists():
        return True
    if not VE_DGEMM_SRC.exists():
        print(f"[ve] NLC DGEMM 源码不存在: {VE_DGEMM_SRC}")
        return False

    inc = NLC_DIR / "include"
    lib = NLC_DIR / "lib"
    cmd = (
        f"ncc -O3 -fopenmp -o {VE_DGEMM_BIN} {VE_DGEMM_SRC} "
        f"-I{inc} -L{lib} -lcblas -lblas_openmp"
    )
    print("[ve] 编译 NLC DGEMM 内核...")
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        print(f"[ve] NLC DGEMM 编译失败:\n{result.stderr}")
        return False

    print(f"[ve] NLC DGEMM 编译成功 → {VE_DGEMM_BIN}")
    return True


def run_ve_kernel(ve_id: int, numa_node: int = -1,
                  auto_numa: bool = True) -> dict:
    """在指定 VE 卡上运行内核

    Args:
        ve_id: VE 编号 (1/2/3, 对应 ve_exec -N)
        numa_node: NUMA 节点 (-1 表示自动选择，>=0 指定节点)
        auto_numa: 自动从 NUMABinder 获取最优 NUMA 绑定 (默认开启)

    Returns:
        dict with status, gflops, elapsed_sec, stdout, stderr
    """
    if not VE_KERNEL_BIN.exists():
        print(f"[ve{ve_id}] 内核二进制不存在，尝试编译...")
        if not compile_ve_kernel():
            return {"status": "fail", "error": "compile failed"}

    print(f"[ve{ve_id}] 运行 ve_exec -N {ve_id}...")

    # NUMA 绑定: 自动选择 > 手动指定 > 不绑定
    prefix = ""
    if auto_numa and numa_node < 0:
        from .numa import best_node as get_best_node
        numa_node = get_best_node(f"ve{ve_id}")
    if numa_node >= 0:
        prefix = f"numactl --cpunodebind={numa_node} --membind={numa_node} "
        print(f"[ve{ve_id}] NUMA 绑定: node {numa_node}")

    cmd = f"{prefix}/opt/nec/ve/bin/ve_exec -N {ve_id} {VE_KERNEL_BIN}"

    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=120
    )

    stdout = result.stdout
    stderr = result.stderr

    gflops = _parse_gflops(stdout)
    elapsed = _parse_elapsed(stdout)

    status = "pass" if (gflops and gflops > 100) else "fail"

    return {
        "status": status,
        "gflops": gflops,
        "elapsed_sec": elapsed,
        "stdout": stdout,
        "stderr": stderr,
    }


def run_ve_dgemm_nlc(ve_id: int, input_file: Path | str, output_file: Path | str,
                     numa_node: int = -1, auto_numa: bool = True) -> dict:
    """在指定 VE 卡上运行 NLC DGEMM 计算
    
    Args:
        ve_id: VE 编号 (1/2/3, 对应 ve_exec -N)
        input_file: 输入矩阵文件路径 (包含 N 及 A、B 矩阵二进制数据)
        output_file: 输出矩阵保存路径
        numa_node: NUMA 节点 (-1 自动选择)
        auto_numa: 自动从 NUMABinder 获取最优 NUMA 绑定
    """
    if not VE_DGEMM_BIN.exists():
        print(f"[ve{ve_id}] NLC DGEMM 二进制不存在，尝试编译...")
        if not compile_ve_dgemm_nlc():
            return {"status": "fail", "error": "compile nlc dgemm failed"}

    # NUMA 绑定
    prefix = ""
    if auto_numa and numa_node < 0:
        from .numa import best_node as get_best_node
        numa_node = get_best_node(f"ve{ve_id}")
    if numa_node >= 0:
        prefix = f"numactl --cpunodebind={numa_node} --membind={numa_node} "

    env = os.environ.copy()
    lib_path = str(NLC_DIR / "lib")
    env["VE_LD_LIBRARY_PATH"] = lib_path

    cmd = f"{prefix}/opt/nec/ve/bin/ve_exec -N {ve_id} {VE_DGEMM_BIN} {input_file} {output_file}"

    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=180, env=env
    )

    stdout = result.stdout
    stderr = result.stderr

    gflops = _parse_gflops_nlc(stdout)
    elapsed = _parse_elapsed(stdout)
    status = "pass" if result.returncode == 0 else "fail"

    return {
        "status": status,
        "gflops": gflops,
        "elapsed_sec": elapsed,
        "stdout": stdout,
        "stderr": stderr,
    }


def _parse_gflops_nlc(text: str) -> float:
    for line in text.splitlines():
        if "GFLOPS" in line:
            try:
                return float(line.split("GFLOPS")[0].split()[-1])
            except (ValueError, IndexError):
                pass
    return 0.0


def _parse_gflops(text: str) -> float:
    for line in text.splitlines():
        if "GFLOPS" in line or "GFlops" in line:
            try:
                return float(line.split(":")[-1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    return 0.0


def _parse_elapsed(text: str) -> float:
    for line in text.splitlines():
        if "Elapsed" in line or "Time" in line:
            try:
                import re
                m = re.search(r'(\d+\.?\d*)\s*(sec|s)', line)
                if m:
                    return float(m.group(1))
            except (ValueError, IndexError):
                pass
    return 0.0
