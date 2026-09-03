# 交付：应用侧短任务接入 Phi Daemon

> 日期: 2026-09-03 03:19:57  
> 范围: dataprep / SpMV / Monte Carlo / multi_task  
> **未改**: TC-002、`run_verify` 峰值 FMA、`bench_pcie` / `spmv_compare`（对照的就是 loadex/scp）

---

## 1. 协议

Daemon 新增（载荷均走 TCP，无 `scp` / `micnativeloadex`）：

| opcode | 名称 | 输入 | 输出 |
| ---: | :--- | :--- | :--- |
| 4 | OP_DATA_CLEAN | `[M,N int32][float64 M×N]` | 同布局，`|x|>3` 换列均值 |
| 5 | OP_PATH_GEN | `pack('ddddiid')` 与原 params.bin 相同 | `valid,invalid` + 均价数组 |
| 6 | OP_CSR_PARTITION | 原 CSR blob | 3 块 `uint32 len + block`（格式同 `csr_partition.c`） |

CSR 输入在卡内拷到对齐缓冲，避免 KNC 未对齐 double 断连。

---

## 2. 现场验证（force 部署新 `.mic` 后）

| 应用 | Phi 步 | Daemon 墙钟 | 正确性 |
| :--- | :--- | ---: | :--- |
| dataprep | 清洗 1024×64 | **0.281 s**（核 0.268 s，含 OpenMP 首次拉起） | std max_diff 3.55e-15；PCA corr 0.997 ✅ |
| SpMV | CSR 分块 N=4096 nnz=167772 | **0.069 s**（核 0.028 s） | max_diff 1.07e-14 ✅ |
| Monte Carlo | 50k 路径 × 252 步 | **0.179 s**（核 0.174 s，计算主导） | vs numpy **0.19%** ✅ |
| multi_task | OP_STATS on input_1 | DAG 中 Phi **~0 s** | checksum 与 ColMajor 参考 **0 差** ✅ |
| 单测 | 17 + clean/path 小规模 | — | **17/17** |

未在本轮对这三条应用重跑 loadex 对照。历史路径是 scp + `micnativeloadex`（装载约 1.3–1.8 s 再加计算）。本轮能严格断言的是：**正确性保持，Phi 步墙钟为上面各行，不再经过装载器。**

峰值 FMA（TC-002 / `run_verify`）仍走 loadex，避免用未对齐的 Daemon FMA 报 GFLOPS。

---

## 3. 代码

- `src/kernels/phi/phi_worker_daemon.c` + 重编译 `.mic`
- `src/scheduler/phi_client.py`：`run_data_clean` / `run_path_gen` / `run_csr_partition`
- 三个 `*_app.py` 与 `examples/multi_task/task_flow.py`
