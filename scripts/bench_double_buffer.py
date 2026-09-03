#!/usr/bin/env python3
"""
bench_double_buffer.py — 多批次串行 vs DoubleBufferedPipeline

对照同一组工作：
  producer: Host 生成 N×N 随机矩阵对（落盘）
  consumer: VE1 NLC DGEMM

串行：每批 gen 完成后再 dgemm。
双缓冲：asyncio 队列深度 2，允许第 k+1 批生成与第 k 批 VE 计算重叠。

判定：双缓冲墙钟 < 串行，且加速比显著大于测量噪声（≥ 1.05×）。
正确性：各批输出 checksum 与 numpy 参考相对误差 < 1e-6。
"""
import asyncio
import os
import struct
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

N = 2048
BATCHES = 4
WORKDIR = PROJECT / "examples" / "pipeline" / "run_data" / "dblbuf"


def _nlc_env():
    env = os.environ.copy()
    env["VE_LD_LIBRARY_PATH"] = "/opt/nec/ve/nlc/3.1.0/lib"
    return env


async def ve_dgemm(inp: Path, out: Path) -> float:
    exe = PROJECT / "src" / "kernels" / "ve" / "dgemm_nlc_ve"
    cmd = f"/opt/nec/ve/bin/ve_exec -N 1 {exe} {inp} {out}"
    t0 = time.time()
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=_nlc_env())
    await proc.communicate()
    return time.time() - t0


def write_pair(path: Path, A, B):
    path.write_bytes(struct.pack("i", N) + A.tobytes() + B.tobytes())


def numpy_checksum(A, B) -> float:
    # dgemm_nlc.c 使用 cblas ColMajor NoTrans，C 序写入的 A,B 在卡上等价于 A.T @ B.T
    return float((A.T @ B.T).sum())


def _produce_sync(batch_id: int):
    import numpy as np
    rng = np.random.default_rng(1000 + batch_id)
    A = rng.normal(0, 0.01, (N, N)).astype(np.float64)
    B = rng.normal(0, 0.01, (N, N)).astype(np.float64)
    inp = WORKDIR / f"in_{batch_id}.bin"
    write_pair(inp, A, B)
    return {"inp": inp, "ref": numpy_checksum(A, B)}


async def produce_batch(batch_id: int):
    # 放到线程，避免同步 numpy 堵住事件循环、让双缓冲无法重叠
    return await asyncio.to_thread(_produce_sync, batch_id)


async def consume_batch(item):
    data = item.data
    out = WORKDIR / f"out_{item.batch_id}.bin"
    elapsed = await ve_dgemm(data["inp"], out)
    raw = out.read_bytes()
    n = struct.unpack_from("i", raw)[0]
    import numpy as np
    C = np.frombuffer(raw[4:], dtype=np.float64)
    got = float(C.sum())
    ref = data["ref"]
    rel = abs(got - ref) / max(abs(ref), 1.0)
    return {"status": "pass" if rel < 1e-6 else "fail",
            "rel_err": rel, "ve_s": elapsed, "checksum": got}


async def run_serial(n_batches: int):
    from scheduler.pipeline import BatchItem
    t0 = time.time()
    results = []
    for i in range(n_batches):
        data = await produce_batch(i)
        item = BatchItem(batch_id=i, data=data, gen_time_sec=0.0)
        results.append(await consume_batch(item))
    return time.time() - t0, results


async def run_pipelined(n_batches: int):
    from scheduler.pipeline import DoubleBufferedPipeline
    pipe = DoubleBufferedPipeline(buffer_size=2)
    t0 = time.time()
    results = await pipe.run(n_batches, produce_batch, consume_batch)
    return time.time() - t0, results


async def main():
    print("=" * 60)
    print(f"  双缓冲对照  N={N}  batches={BATCHES}  VE1 NLC DGEMM")
    print("=" * 60)
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # warmup VE
    await produce_batch(99)
    await ve_dgemm(WORKDIR / "in_99.bin", WORKDIR / "out_99.bin")

    serial_s, serial_r = await run_serial(BATCHES)
    pipe_s, pipe_r = await run_pipelined(BATCHES)

    def summarize(tag, wall, rows):
        fails = [r for r in rows if r.get("status") != "pass"]
        max_err = max(r["rel_err"] for r in rows)
        prod = [r.get("producer_elapsed", 0.0) for r in rows]
        cons = [r.get("consumer_elapsed", r.get("ve_s", 0.0)) for r in rows]
        print(f"  {tag}: wall={wall:.3f}s  max_rel_err={max_err:.2e}  "
              f"fail={len(fails)}/{len(rows)}")
        if any(prod):
            print(f"         mean gen={sum(prod)/len(prod):.3f}s  "
                  f"mean ve={sum(cons)/len(cons):.3f}s")
        return len(fails) == 0

    ok_s = summarize("串行", serial_s, serial_r)
    ok_p = summarize("双缓冲", pipe_s, pipe_r)
    speedup = serial_s / pipe_s if pipe_s > 0 else 0.0
    print(f"  加速比: {speedup:.3f}×  (通过线 ≥ 1.05× 且两边 checksum 合格)")

    passed = ok_s and ok_p and speedup >= 1.05
    print("  ✅ 通过" if passed else "  ⚠️ 未达标准（可能重叠收益被 ve_exec 启动淹没）")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
