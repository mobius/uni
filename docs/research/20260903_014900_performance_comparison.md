# 分支与主线基线性能对比分析报告 (Performance Comparison)

> 报告日期: 2026-09-03 01:49:00  
> 对比基准: `origin/master` (Week 6 终期验收基线) vs `feature/hetero-optimization-v2`  
> 测试环境: ASUS ESC4000 G4 (2× Xeon Gold 6252, 1× Phi 7120P, 3× NEC VE 1.0)  
> 责任 Agent: Antigravity (Google DeepMind)  

---

## 1. 核心算子与算力对比 (Core Compute & Roofline)

| 测试项 / 算子 | 主线历史早期/基线 | 当前 Feature 分支 | 提升幅度 (Speedup) | 备注说明 |
| :--- | :--- | :--- | :--- | :--- |
| **VE 基础矩阵乘 (DGEMM N=512)** | 64 GFLOPS (naive 三重循环) | **1,119 GFLOPS** (调度层 NLC 集成) | **17.5× (提升 1648%)** | 彻底突破 HBM 访问未命中造成的内存墙瓶颈 |
| **VE 大矩阵乘 (DGEMM N=2048)** | 未完全 API 抽象 | **1,725 GFLOPS** (单卡 81% 峰值) | **~27× (相比 naive)** | 3 卡合计达到 **5.08 TFLOPS** 稠密矩阵乘吞吐 |
| **全卡并行吞吐 (TC-002)** | 5.68 ~ 5.76 TFLOPS | **5.65 ~ 5.76 TFLOPS** | 维持在设计峰值 | 4 卡协同稳定，符合预期 |
| **Phi 7120P FMA 峰值** | 569 GFLOPS | **571 ~ 586 GFLOPS** | 稳定在 99%~102% | 达到 KNC 架构物理计算极限 |

---

## 2. 调度框架与流水线能力对比 (Scheduler & Pipeline Capabilities)

| 维度 | 主线版本 (`master`) | 当前 Feature 分支 (`feature/hetero-optimization-v2`) | 收益与架构意义 |
| :--- | :--- | :--- | :--- |
| **NLC DGEMM 调用模式** | 需在脚本/应用层手工拼接 shell 与环境路径 | `ve.run_ve_dgemm_nlc()` 标准化调度 API，自动绑定 NUMA 与环境库 | 代码解耦，消除各示例脚本中的命令冗余 |
| **流水线并发范式** | 静态串行阻塞（先落盘全部数据，再触发加速卡） | **`DoubleBufferedPipeline` 异步双缓冲引擎** | 支持 $K$ 批次计算与 $K+1$ 批次预处理在后台重叠重合 |
| **测试套件健壮性** | 13 项单元测试 | **15 项单元测试全部 PASS** | 覆盖了 NLC 接口及双缓冲异步流水线 |
| **工程化治理体系** | 缺少统一规范文档与术语留档 | 完备的 `AGENTS.md`、`docs/glossary.md` 与分层架构规范 | 标准化开发，无敏感信息泄露 |

---

## 3. 瓶颈现状复盘 (Next Bottlenecks to Tackle)

1. **小矩阵计算耗时与启动开销**：
   - 在 $N=512$ 规模下，NLC 实际计算仅需 ~0.002s，但进程启动及环境加载耗时约 0.10s。矩阵规模增大到 $N=2048$ 时，利用率迅速攀升至 80%+。
2. **Phi 启动时延依然是全局关键路径**：
   - 无论 Basic 还是 Multi-Task，只要涉及 Phi，总耗时即被 Phi 的 `micnativeloadex` 开销（~1.7s~2.5s）决定。这为我们后续推进 **Phase 6 (Phi 常驻 Daemon 进程池)** 提供了强力的数据支撑。
