#!/usr/bin/env python3
"""
bench_pipeline_latency.py — TC-HETERO-003: 流水线延迟对比

对比两条数据流水线:
  A) 纯 VE 链: gen → VE1(dgemm) → VE2(scale) → VE3(transpose) → host
  B) 含 Phi 链: gen → VE1(dgemm) → VE2(scale) → Phi(stats) → host

测量「在纯 VE 链末尾增加 Phi stats」的增量延迟。

链 B（本分支默认）走常驻 Daemon 的 OP_STATS，对 c3.bin 做 min/max/mean/stddev。
另报一臂历史对照：同一 VE 链 + micnativeloadex peak_fp64.mic（旧脚本把这步误标为 stats）。

通过标准: Daemon 臂相对纯 VE 的 overhead ≤ 20%。
"""

import sys, os, time, struct, asyncio, subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

N = 512
MIC_LIBS = PROJECT.parent / "intel_phi" / "icc_mic_libs"


def shell(cmd, timeout=120, env=None):
    t0 = time.time()
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=timeout, env=env)
    return r.returncode, r.stdout.strip(), r.stderr.strip(), time.time() - t0


def ensure_compiled():
    kv = PROJECT / "src" / "kernels" / "ve"
    for name, src, extra in [
        ("dgemm_nlc_ve", "dgemm_nlc.c",
         "-I/opt/nec/ve/nlc/3.1.0/include -L/opt/nec/ve/nlc/3.1.0/lib "
         "-lcblas -lblas_openmp"),
        ("scale_ve", "scale.c", ""),
        ("transpose_ve", "transpose.c", ""),
    ]:
        if not (kv / name).exists():
            rc, _, err, _ = shell(
                f"ncc -O3 -fopenmp {extra} -o {kv/name} {kv/src}")
            if rc != 0:
                print(f"[compile] {name} FAILED")
                return False
    return True


def gen_data(wd: Path) -> Path:
    import numpy as np
    wd.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(42)
    A = rng.normal(0, 0.01, (N, N)).astype(np.float64)
    B = rng.normal(0, 0.01, (N, N)).astype(np.float64)
    data = struct.pack("i", N) + A.tobytes() + B.tobytes()
    path = wd / "input.bin"
    path.write_bytes(data)
    return path


async def run_ve_cmd(ve_id: int, exe: str, args: str,
                     nlc_env: bool = False) -> float:
    """Run a VE command, return elapsed seconds"""
    kv = PROJECT / "src" / "kernels" / "ve"
    env = os.environ.copy()
    if nlc_env:
        env["VE_LD_LIBRARY_PATH"] = "/opt/nec/ve/nlc/3.1.0/lib"

    cmd = f"/opt/nec/ve/bin/ve_exec -N {ve_id} {kv/exe} {args}"
    t0 = time.time()
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env)
    await proc.communicate()
    return time.time() - t0


async def run_phi_loadex(exe: str) -> float:
    """Historical path: micnativeloadex (full binary reload)."""
    kp = PROJECT / "src" / "kernels" / "phi"
    env = os.environ.copy()
    if MIC_LIBS.is_dir():
        env["SINK_LD_LIBRARY_PATH"] = str(MIC_LIBS)

    cmd = f"micnativeloadex {kp/exe} -d 0 -t 60"
    t0 = time.time()
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env)
    await proc.communicate()
    return time.time() - t0


def run_phi_daemon_stats(matrix_path: Path) -> tuple[float, dict]:
    """Resident daemon OP_STATS on [int32 N][float64 N*N]."""
    from scheduler.phi_client import PhiDaemonManager
    raw = matrix_path.read_bytes()
    n = struct.unpack_from("<i", raw)[0]
    body = raw[4:]
    mgr = PhiDaemonManager()
    if not mgr.start_daemon():
        raise RuntimeError("phi daemon not available")
    t0 = time.time()
    res = mgr.run_stats(n, body)
    elapsed = time.time() - t0
    if res.get("status") != "pass":
        raise RuntimeError(f"daemon stats failed: {res}")
    return elapsed, res


async def chain_A(wd: Path) -> list[tuple[str, str, float]]:
    """Pure VE chain: gen → dgemm(VE1) → scale(VE2) → transpose(VE3) → host"""
    steps = []

    # Step 1: gen (host)
    t0 = time.time()
    inp = gen_data(wd)
    elapsed = time.time() - t0
    steps.append(("gen", "host", elapsed))

    # Step 2: dgemm (VE1)
    elapsed = await run_ve_cmd(1, "dgemm_nlc_ve",
                               f"{inp} {wd}/c1.bin", nlc_env=True)
    steps.append(("dgemm", "ve1", elapsed))

    # Step 3: scale (VE2)
    elapsed = await run_ve_cmd(2, "scale_ve",
                               f"{wd}/c1.bin {wd}/c2.bin")
    steps.append(("scale", "ve2", elapsed))

    # Step 4: transpose (VE3)
    elapsed = await run_ve_cmd(3, "transpose_ve",
                               f"{wd}/c2.bin {wd}/c3.bin")
    steps.append(("transpose", "ve3", elapsed))

    return steps


async def main():
    print("=" * 60)
    print("  TC-HETERO-003: 流水线延迟对比")
    print("=" * 60)

    if not ensure_compiled():
        print("  ❌ 编译失败")
        return

    wd = PROJECT / "examples" / "pipeline" / "run_data"

    from scheduler.phi_client import PhiDaemonManager
    mgr = PhiDaemonManager()
    if not mgr.start_daemon():
        print("  ❌ Phi daemon 无法启动")
        return
    ping = mgr.ping()
    print(f"\n[warmup] daemon ping status={ping.get('status')} "
          f"rtt={ping.get('total_roundtrip_sec', 0)*1e3:.2f} ms")

    def dump(title, steps):
        print(f"\n--- {title} ---")
        total = sum(s[2] for s in steps)
        for name, dev, t in steps:
            print(f"  {name:<12} [{dev:<12}] {t:.4f}s")
        print(f"  合计: {total:.4f}s")
        return total

    # 预热：numpy 导入、VE 启动、Daemon 线程池，避免把一次性成本算进某一臂
    gen_data(wd)
    await run_ve_cmd(1, "dgemm_nlc_ve", f"{wd}/input.bin {wd}/c1.bin", nlc_env=True)
    run_phi_daemon_stats(wd / "c1.bin")

    steps_A = await chain_A(wd)
    total_A = dump("链 A: 纯 VE", steps_A)

    stats_s, stats_res = run_phi_daemon_stats(wd / "c3.bin")
    print(f"\n--- 链 B 增量: Daemon OP_STATS on c3 ---")
    print(f"  stats        [phi0-daemon ] {stats_s:.4f}s  "
          f"min={stats_res.get('min'):.6f} max={stats_res.get('max'):.6f}")
    total_B = total_A + stats_s
    print(f"  合计 A+stats: {total_B:.4f}s")

    loadex_s = await run_phi_loadex("peak_fp64.mic")
    print(f"\n--- 历史对照增量: micnativeloadex peak_fp64 ---")
    print(f"  fma_loadex   [phi0-loadex ] {loadex_s:.4f}s")
    total_L = total_A + loadex_s
    print(f"  合计 A+loadex: {total_L:.4f}s")

    overhead_pct = (total_B - total_A) / total_A * 100 if total_A > 0 else 0
    overhead_loadex = (total_L - total_A) / total_A * 100 if total_A > 0 else 0

    print("\n" + "=" * 60)
    print("  对比")
    print("=" * 60)
    print(f"  纯 VE 链:  {total_A:.4f}s")
    print(f"  含 Phi 链: {total_B:.4f}s")
    print(f"  Phi 开销:  {total_B - total_A:.4f}s")
    print(f"  Overhead:  {overhead_pct:.1f}%")
    print(f"  历史对照 loadex overhead: {overhead_loadex:.0f}% ({total_L:.4f}s)")
    print(f"  通过标准:  Daemon 臂 ≤ 20%")

    if overhead_pct <= 20:
        print(f"  ✅ 通过")
    else:
        print(f"  ⚠️ 未达标准 (Daemon stats 增量 {total_B - total_A:.4f}s)")


if __name__ == "__main__":
    asyncio.run(main())
