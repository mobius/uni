# Feature 分支文档优化收益审计

> 日期: 2026-09-03 02:52:00  
> 对照: `feature/hetero-optimization-v2` 文档声明 vs 代码路径 vs 同机现场实测（见 `20260903_024928_master_vs_feature_perf.md`）  
> 主线: `master` @ `e7f87b9`（仓库无 `main`）

判定：✅ 数字量级正确　⚠️ 数字对但口径误导　❌ 与代码/实测不符

---

## 1. 总评

文档把 **三件不同的事** 叠在一起写成“相对主线的优化收益”：

1. **NLC vs naive DGEMM**（主线验收前就已在 `bench_throughput.py` 里跑 NLC，不是本分支相对 `master` 的增量）。
2. **Phi Daemon PING vs `micnativeloadex` 装载**（交互延迟确实降了三个数量级，但 README 把 **TC-003 流水线用例改写成了心跳**）。
3. **自适应调度微基准**（CPU 侧 μs 级开销属实，但调度器是算子名 if/else，不是完整 Roofline 求解）。

现场 TC-002：master **5.61 TFLOPS**，feature **5.62 TFLOPS**。峰值吞吐声明成“分支突破”不成立。

---

## 2. 逐条核对

### 2.1 README / 关键技术突破

| 声明 | 判定 | 说明 |
| :--- | :---: | :--- |
| NLC DGEMM **1,750 GFLOPS、81% 极限** | ⚠️ | 相对 VE 单卡理论 ~2,160 GFLOPS，1750/2160=81% 口径对。本机 N=2048 实测 **1,688–1,730 GFLOPS（约 78–80%）**，1750 是历史最好档，不是每次都能打到。相对 naive 64 GFLOPS 的 25× 是 **算法库切换**，`master` 的 TC-002 已用同一 NLC。 |
| Phi 心跳 **2.0 s → 0.4 ms，近 5,000×** | ⚠️/❌ | 数量级方向对：装载墙钟 ~1.3–1.8 s，Daemon PING 本机 **0.86–2.21 ms（中位 ~1.4 ms）**，不是稳定 0.41 ms。用 2000/0.41≈4878 得到“5000×”；用实测中位约 **1,400×**。PING ≠ 计算任务；Daemon `OP_FMA_PEAK` 本机 1.58 s、**124 GFLOPS**，与 `peak_fp64.mic` **627 GFLOPS** 工作量未对齐。 |
| AdaptiveDispatcher **2.15 μs** | ✅ | 本机 `adaptive_bench.py`：**2.01 μs/次、4.97×10⁵/s**。量级正确。 |
| `DoubleBufferedPipeline` 计算与 I/O 重叠 | ⚠️ | 类存在，**仅 `tests/test_scheduler.py` 用假 producer/consumer**。`examples/pipeline/pipeline.py` 仍是串行 DAG + `micnativeloadex`，无端到端重叠收益数据。 |
| TC-003 = **0.41 ms Daemon，攻克** | ❌（文档已改） | 原 TC-003 是纯 VE vs 含 Phi **流水线墙钟**，通过线 overhead≤20%。本机两边都是 **~2.0 s / overhead ~370%**。中英 README 现已改回该定义并对齐。 |
| TC-002 **5.56–5.76 TFLOPS** | ✅ | 本机 5.62，落在区间。这是平台能力，**不是 feature 相对 master 的提升**（master 5.61）。 |
| `examples/basic` **3,277 GFLOPS** | ⚠️ | 未在本轮重跑；与 TC-002 5.6 TFLOPS 不是同一内核组合，容易被当成“总峰值”。 |
| 单元测试 **17 项全绿** | ✅ | `test_scheduler.py` 确有 17 个 `test_*`。`test_phi_daemon_manager` 会真启 Daemon，断言 RTT **<50 ms**，约束很松，不能支撑 0.41 ms。 |
| Phase 3 “4/6 通过” 同时 TC-003 标 ✅ | ❌ | 自相矛盾：进度表仍写 4/6，结果表把 TC-003 改成通过。 |

### 2.2 `docs/research/20260903_014900_performance_comparison.md`

| 声明 | 判定 | 说明 |
| :--- | :---: | :--- |
| 表头：主线 vs feature | ❌ | 左列混用 **“主线历史早期 naive”** 与 **“主线当前 NLC 吞吐”**。N=512 的 17.5×、N=2048 的 ~27× 是 **naive→NLC**，不是 `e7f87b9`→feature。 |
| N=2048 **81% 峰值、3 卡 5.08 TFLOPS** | ⚠️ | 5.08 是三卡 DGEMM 之和，不含 Phi。本机三卡约 **5.13 TFLOPS**。81% 偏乐观（见上）。 |
| TC-002 主线 5.68–5.76 vs feature 5.65–5.76 **维持峰值** | ✅ | 与本轮打平结论一致。 |
| Phi **571–586 GFLOPS = 99%–102% 物理极限** | ❌ | `peak_fp64.c` 自己写的理论是 **61×1.238 GHz×8×2 ≈ 1.208 TFLOPS**。586/1208≈**48%**。99–102% 是相对某次 **569 GFLOPS 旧实测**，不是 KNC 物理极限。本机 FMA **484–627 GFLOPS**，随装载/线程波动。 |
| master 流水线“静态串行”、feature 双缓冲 | ⚠️ | 能力声明；**示例与 TC-003 仍串行**。 |
| 文末仍写 Phi `micnativeloadex` 1.7–2.5 s 是关键路径、Phase 6 待做 | ⚠️ | 与后写的 Phase 6“已突破 0.4 ms”并置，读者会以为流水线已改完。 |

### 2.3 Phase 6 交付 `...020500_phase6_phi_daemon_delivery.md`

- Daemon + 32 字节头 + `phi_client.py`：**代码属实**。
- **0.41 ms、5000×**：本机复现不到 0.41 ms；倍数依赖把“装载墙钟”和“空 PING”比在一起（方向对，精度和口径夸大）。
- “毫秒级多任务与细粒度流式计算”：**未接到** `bench_pipeline_latency.py` / `examples/pipeline`。
- 测试 16/16：随后 Phase 7 写成 17，与 README 17 一致；16 是中间快照，不算错。

### 2.4 Phase 7 / `...023000_adaptive_dispatcher_benchmark.md`

| 声明 | 判定 | 说明 |
| :--- | :---: | :--- |
| 2.15 μs、46.4 万次/s、DAG 0.59 ms | ✅ | 本机 2.01 μs、49.7 万、0.51 ms。 |
| “基于 Roofline 智能路由” | ⚠️ | `dispatcher.py` 是 **算子名集合 + N≤128→host + VE 轮询**。`Profiler.estimate` 只填 `estimated_*`，**没有**用算术强度选设备。`stats` 一律 host，与流水线把 stats 放 Phi 的旧设计相反。 |
| 三卡 1,710/1,714/1,664 → 5.08 TFLOPS | ✅ 量级 | 与调度器无关，仍是 NLC 内核。 |
| 四卡 5.56–5.65 TFLOPS | ✅ | 本机 5.62。 |

### 2.5 Phase 5 交付

- `run_ve_dgemm_nlc()` API：**属实**（相对 master 是封装，不是新算力）。
- N=512 **~1119 GFLOPS vs naive 64、~18×**：**历史测量可信**，小矩阵利用率被 `ve_exec` 启动吃掉（文档自己也写了 ~0.10 s 启动 vs ~0.002 s 计算）。
- 把 1119 写进“相对主线”对比表：**误导**（主线脚本同样链 NLC）。

---

## 3. 文档已按下列口径修订（2026-09-03）

已改：`README.md`、`README_en.md`、`docs/research/20260903_014900_performance_comparison.md`、Phase 6/7 交付中的夸大句、自适应评测第 2 节、`docs/glossary.md` 中 Adaptive Dispatcher 定义。

原稿数字仍可在 git 历史中查看；**对外以修正后的 README 与 014900 为准**。

## 3b. 正确表述（摘要）

1. **相对 `master`**：TC-002/TC-003 打平；增量是 NLC/Daemon **API**、双缓冲 **模板**、自适应 **路由原型**、Phi PING **毫秒级**。
2. **相对 naive DGEMM**：NLC 约 17×（N=512）～25×（N=2048），这是 6 月结论 2，不要写成 9 月 feature vs master。
3. **Phi**：装载 ~1.5–2 s；Daemon PING ~1 ms 量级（本机 0.9–2.2 ms）。禁止把 PING 写成 TC-003 通过。禁止写“达到 KNC 物理极限”。
4. **双缓冲 / 自适应**：标明“单元测试覆盖，尚未替换 `examples/pipeline` 与 TC-003”。
5. 中英 README 对齐 TC-003 状态。

---

## 4. 术语

本审计沿用已有词：NLC、Roofline、Double Buffering、Adaptive Dispatcher、Phi Worker Daemon（见 `docs/glossary.md`）。  
**偷换测试定义**：同一用例编号（如 TC-003）改测完全不同的指标却沿用“通过”。
