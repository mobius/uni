# 主线 (`master`) vs Feature 分支现场性能对比

> 报告日期: 2026-09-03 02:49:28  
> 对比: `master` @ `e7f87b9`（Week 6 验收） vs `feature/hetero-optimization-v2` @ `2ac8370`  
> 说明: 仓库没有名为 `main` 的分支，主线是 `master`。  
> 环境: ASUS ESC4000 G4；VEOS 三卡 ONLINE；Phi 7120P Die 37 °C；loadavg 0.50  
> 方法: feature 在工作区直接跑；master 用 git worktree 隔离；Phi 统一 `SINK_LD_LIBRARY_PATH=/home/joey/Work/intel_phi/icc_mic_libs`

---

## 1. 结论（先看这里）

在 **同一套 TC-002 / TC-003 脚本**（3×VE NLC DGEMM N=2048 + Phi `micnativeloadex` FMA / stats）上，**两分支算力和流水线延迟基本打平**。

Feature 的收益不在这条“进程级满载吞吐”路径上，而在调度层能力：

| 能力 | master | feature | 实测差异 |
| :--- | :--- | :--- | :--- |
| 四卡合计吞吐 (TC-002) | **5.61 TFLOPS** | **5.62 TFLOPS** | +0.2%，测量噪声 |
| 纯 VE 流水线 (TC-003 A) | 0.43 s | 0.42 s | 持平 |
| 含 Phi 流水线 (TC-003 B) | 1.99 s（Phi stats 1.78 s） | 2.00 s（Phi stats 1.78 s） | 持平；瓶颈仍是 `micnativeloadex` |
| 自适应路由 | 无 | 2.01 μs / 次，4.97×10⁵ 决策/s | 新能力，开销可忽略 |
| Phi 任务交互 | 每次装载 ~1.3–1.8 s | Daemon PING **0.9–2.2 ms** | 交互延迟约 **10³×** 改善 |

---

## 2. TC-002 数据中心吞吐（公平重跑）

目标: 3×VE `cblas_dgemm` N=2048 + Phi FP64 FMA，合计 ≥ 5.0 TFLOPS。

| 设备 | master GFLOPS (墙钟) | feature GFLOPS (墙钟) |
| :--- | :--- | :--- |
| VE1 DGEMM | 1694 (0.16 s) | 1730 (0.81 s) |
| VE2 DGEMM | 1713 (0.17 s) | 1710 (0.86 s) |
| VE3 DGEMM | 1720 (0.17 s) | 1688 (0.73 s) |
| Phi FMA | 484 (1.85 s) | 494 (1.84 s) |
| **合计** | **5.61 TFLOPS / 1.85 s** | **5.62 TFLOPS / 1.84 s** |

VE 墙钟差来自 `ve_exec` 启动与排队，**GFLOPS 由核内计时解析，两分支同一 NLC 二进制量级（1.69–1.73 TFLOPS/卡）**。并行墙钟被 Phi 装载（~1.85 s）主导。

**失败对照（不可用于对比）**: 在 `/tmp/uni-master` worktree 中，`MIC_LIBS` 解析到 `/tmp/intel_phi/...`，Phi 报 0 GFLOPS。补上 `SINK_LD_LIBRARY_PATH` 后才得到上表。

---

## 3. TC-003 流水线延迟

| 链 | master | feature |
| :--- | :--- | :--- |
| A 纯 VE (gen→dgemm→scale→transpose) | 0.43 s | 0.42 s |
| B 含 Phi stats | 1.99 s | 2.00 s |
| Phi 相对开销 | +368% | +373% |

两分支 **都未达到** “Phi overhead ≤ 20%” 的 TC-003 通过线，原因相同：`micnativeloadex` 装载 ~1.78 s，不是 PCIe 中转。

Feature 的 Phi Daemon **没有接到这条 bench 脚本上**（脚本仍走 `micnativeloadex`），所以 TC-003 看不出 Phase 6 收益。

---

## 4. Feature 独有路径实测

### 4.1 自适应调度器（仅 feature）

`examples/adaptive_bench.py`：30 000 次 `dispatch()`。

- 单次决策 **2.01 μs**
- 吞吐 **496 584 次/s**
- 100 节点 DAG 装配 **0.51 ms**

相对一次 VE `ve_exec`（~0.1 s）或 Phi 装载（~1.8 s），调度本身不是瓶颈。

### 4.2 Phi Daemon vs `micnativeloadex`

Daemon 已在卡内监听 `172.31.1.1:19800`。

| 操作 | 延迟 | 备注 |
| :--- | :--- | :--- |
| Daemon PING（8 次） | 0.86–2.21 ms（中位 ~1.4 ms） | 不含重装载 |
| Daemon `OP_FMA_PEAK` | 往返 1.58 s，上报 124 GFLOPS | 卡内核参数/迭代与 `peak_fp64.mic` 不一致，**不能**当峰值对比 |
| `micnativeloadex peak_fp64.mic` | 墙钟 1.75 s，核内 0.41 s，**627 GFLOPS** | 装载开销 ≈ 1.34 s |

交互路径从秒级掉到毫秒级；**峰值 FLOPS 仍应以 `peak_fp64.mic` / TC-002 为准**，Daemon FMA opcode 尚未对齐同一工作量。

---

## 5. 架构差异（为何吞吐打平）

`master` 已在验收期接入 NLC DGEMM 与四卡并行脚本。`feature` 增量主要是：

1. `ve.run_ve_dgemm_nlc()` 与 NUMA 绑定封装（同一 NLC）
2. `DoubleBufferedPipeline`（本轮未改 TC-003，故无端到端差）
3. Phi 常驻 Daemon（TC-002/003 未使用）
4. Roofline 自适应调度器（CPU 微秒级）

因此：**峰值吞吐平台期已在 master 达到；feature 优化的是调用模型与小任务延迟。**

---

## 6. 后续要对齐的测量

1. 把 TC-003 链 B 的 Phi 步切到 Daemon，再测 overhead 是否能落到 ≤20%。
2. 对齐 Daemon `OP_FMA_PEAK` 与 `peak_fp64.c` 的迭代/线程配置。
3. 用真实多批次 producer/consumer 对比串行 vs `DoubleBufferedPipeline` 墙钟。
