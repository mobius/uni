# Uni — Intel Phi 7120P + NEC VE 1.0×3 Heterogeneous Computing Project

> Server: ASUS ESC4000 G4, 2× Xeon Gold 6252, Rocky Linux 8.10  
> Accelerators: 1× Intel Xeon Phi 7120P (KNC) + 3× NEC Vector Engine 1.0  
> Default branch is **`master`** (there is no `main`). Feature work lives on `feature/hetero-optimization-v2`.

## Objective

Heterogeneous compute co-scheduling on a single ESC4000 G4, matching Phi and VE to complementary workloads.

## Compute Capacity

| Metric | Phi 7120P | VE 1.0×3 | **Total** |
|------|----------|---------|---------|
| FP64 Theoretical | 1.21 TFLOPS | 6.48 TFLOPS | **7.69 TFLOPS** |
| FP64 Achievable (planning) | ~0.58 TFLOPS | ~5.25 TFLOPS | **~5.83 TFLOPS** |
| Memory | 16 GB GDDR5 | 144 GB HBM2 | **160 GB** |
| Memory BW | 157 GB/s | 3,186 GB/s | **3,343 GB/s** |

Phi FMA on this machine is about **0.48–0.63 TFLOPS** (~40–52% of 1.21), not “KNC peak”. VE NLC DGEMM N=2048 is about **1.69–1.73 TFLOPS/card** (~78–80% of ~2.16).

## Progress

| Phase | Content | Status |
|-------|------|------|
| 0 | Hardware verification | ✅ |
| 1 | Software stack (uv/ncc/ICC) | ✅ |
| 2 | Core scheduler | ✅ |
| 3 | Benchmarks TC-001–006 | ✅ 4/6 pass; TC-003 pipeline still load-bound |
| 4 | Apps (SpMV + prep + MC) | ✅ |
| 5 | NLC API + double-buffer **template** | ✅ Template tested; examples still serial |
| 6 | Phi resident daemon | ✅ OP_STATS wired into TC-003 / examples/pipeline |
| 7.1 | Adaptive dispatcher prototype | 🚀 Opcode+size routing; ~2 μs; not a full Roofline solver |

## Quick Start

```bash
bash scripts/check_hw.sh

cd env && uv venv && source .venv/bin/activate && uv pip install numpy rich
cd ..

bash examples/basic/run.sh          # 4-card FMA baseline (not the same metric as TC-002)
./env/.venv/bin/python3 scripts/bench_throughput.py  # ~5.6 TFLOPS on this host
./env/.venv/bin/python3 scripts/bench_pcie.py
./env/.venv/bin/python3 scripts/bench_mpi.py

./env/.venv/bin/python3 src/apps/hetero_spmv/spmv_app.py
./env/.venv/bin/python3 src/apps/hetero_dataprep/dataprep_app.py
./env/.venv/bin/python3 src/apps/monte_carlo/mc_app.py

bash scripts/run_all.sh 2>&1 | tee acceptance.log
```

## Benchmark Results

| Test | Metric | Result | Verdict |
|------|------|------|------|
| TC-001 PCIe BW | 3×VE concurrent H2D | 13.7 GB/s (86% eff) | ⚠️ |
| TC-002 Throughput | 4-card N=2048 | **~5.56–5.76 TFLOPS** (live 5.62) | ✅ vs ≥5.0; **tied with `master` (5.61)** |
| TC-003 Pipeline | VE-only + daemon OP_STATS increment | VE 0.324 s; stats **21.9 ms**; **6.8%** overhead | ✅ ≤20%; loadex FMA control **580%** |
| TC-004 MPI | 3-card ring | **97.8%** | ✅ |
| Phi daemon PING | heartbeat RTT | **0.4–1.0 ms** after warmup | N=512 stats RTT ~20 ms (2 MB payload) |
| Dispatch microbench | `dispatch()` | live **~2.0 μs** | CPU only |

Live comparison: `docs/research/20260903_024928_master_vs_feature_perf.md`.  
Claim audit: `docs/research/20260903_025200_feature_claim_audit.md`.

## Applications

| App | Path | Flow | Result |
|------|------|------|------|
| Hetero SpMV | `src/apps/hetero_spmv/` | Host→Phi partition→3VE | 0.107s, max_diff 1.07e-14 |
| Data Prep | `src/apps/hetero_dataprep/` | Phi clean→VE1 std→VE2 PCA | corr 0.997, std diff 3.55e-15 |
| Monte Carlo | `src/apps/monte_carlo/` | Phi paths→3VE payoff | diff 0.15% vs numpy |

## Scheduler (feature)

```
TaskGraph (DAG, optional device="auto")
  ├── AdaptiveDispatcher → opcode + N heuristics, VE round-robin (~2 μs)
  ├── NUMABinder / PowerCap (1440 W)
  ├── PhiClient → resident daemon (PING ~1 ms; OP_STATS on the pipeline)
  ├── VERunner → NLC DGEMM helper (~1.7 TFLOPS/card at N=2048)
  └── DoubleBufferedPipeline → unit-tested template only
```

Naive DGEMM (~64 GFLOPS) → NLC is a **library** win already used by `master` TC-002. Do not report it as feature-vs-master speedup.

Double-buffer bench (`scripts/bench_double_buffer.py`, N=2048 × 4) matches checksums but **no wall-clock speedup** (0.95×): host generation dominates and contends with `ve_exec`.

## Key Constraints

- **PCIe Gen3 ×16**: ~15.75 GB/s vs multi-TB/s on-card
- **PSU 1600 W**: PowerCap budget 1440 W
- **Phi passive cooling**: Slot 1
- **Split toolchains**: ICC 16.0 (`-mmic`) vs ncc; Phi I/O via scp
