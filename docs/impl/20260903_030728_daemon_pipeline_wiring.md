# 交付：Phi Daemon 接入流水线 + 双缓冲对照

> 日期: 2026-09-03 03:07:28  
> 分支: feature/hetero-optimization-v2  
> 验证原则: 增量口径、numpy 对照、历史 loadex 同场、失败如实记录

---

## 1. 做了什么

1. Daemon 新增 **OP_STATS=3**：载荷 `[int32 N][float64 N×N]`，回传 min/max/mean/stddev。矩阵拷到 64B 对齐缓冲后再 OpenMP（KNC 上对 `payload+4` 直接解引用会断连接）。
2. `PhiDaemonManager.start_daemon(force=True)`：`killall` + scp 新二进制，避免端口占用留下旧进程。
3. **TC-003**（`scripts/bench_pipeline_latency.py`）：
   - 预热 numpy / VE / Daemon 线程池后测纯 VE 链；
   - **B 臂 = 同一 A 的墙钟 + 对该次 c3.bin 的 Daemon stats**（不重跑 gen，避免把首次 import 算进某一臂）；
   - 同场对照：同一增量定义下的 `micnativeloadex peak_fp64.mic`。
4. `examples/pipeline/pipeline.py` 的 Phi 步改为 Daemon stats；numpy 参考改为与 `cblas` ColMajor 一致（`C1 ≡ B @ A`）。
5. `scripts/bench_double_buffer.py`：多批次 Host 生成 vs VE1 NLC DGEMM，checksum 用同一 ColMajor 约定；producer 走 `asyncio.to_thread`。

未做：把 `OP_FMA_PEAK` 改成 AVX-512 `peak_fp64.mic` 同源内核（C 侧仍是标量 FMA，注释写明不可比）。

---

## 2. 验证结果（本机 2026-09-03）

### 2.1 正确性

| 项 | 结果 |
| :--- | :--- |
| 单元测试 | **17/17 PASS**（含 N=32 Daemon stats vs numpy，min/max/mean 1e-9，std 1e-6） |
| N=512 / N=64 stats vs numpy | min 差 0 |
| `examples/pipeline` checksum | 相对误差 **9.56e-16**；Host vs Phi min/max 差 0 |
| 双缓冲 4 批 N=2048 | max rel err **9.17e-15**，0 fail |

### 2.2 TC-003 延迟（预热后）

| 臂 | 墙钟 | 相对纯 VE |
| :--- | ---: | ---: |
| A 纯 VE（gen+dgemm+scale+transpose） | **0.3235 s** | — |
| Daemon OP_STATS（仅增量） | **0.0219 s** | **+6.8%** ✅ ≤20% |
| A + stats | 0.3454 s | |
| 对照 loadex peak_fp64 增量 | **1.8769 s** | **+580%** |

PING 预热后 0.40–0.63 ms。N=512 stats：首次含 OpenMP 拉起 ~260–290 ms；稳态往返 ~20 ms，核内 ~0.12–2.3 ms，其余为 2 MB 载荷与 virtio。

旧脚本把链 B 的 Phi 步做成 `peak_fp64.mic` 且重跑 gen，**不能**与本表直接横比。

### 2.3 双缓冲（未通过加速线）

N=2048，4 批，VE1 NLC DGEMM：

| | 墙钟 | checksum |
| :--- | ---: | :--- |
| 串行 | 3.523 s | 合格 |
| DoubleBufferedPipeline(depth=2) | 3.720 s | 合格 |
| 加速比 | **0.947×** | 线 1.05× **未达到** |

流水线侧 mean gen **0.826 s**、mean ve **0.438 s**。Host 生成是长杆且与 VE 争带宽，重叠没有缩短墙钟。结论写进 README，不把模板存在当成收益。

---

## 3. 代码与回归注意

- 部署新 `.mic` 必须 `start_daemon(force=True)`，否则 19800 上仍是旧进程（本次排障：bind in use + 19 998 字节旧文件）。
- 比较 numpy 与 NLC 输出时必须按 ColMajor 解释 C 序缓冲。
- `producer_fn` 若同步占满事件循环，双缓冲不会重叠；bench 已 `to_thread`。
