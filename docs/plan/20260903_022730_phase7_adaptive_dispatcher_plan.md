# Phase 7.1 实施计划: 基于 Roofline 模型的自适应算子调度器 (Adaptive Dispatcher)

> 日期: 2026-09-03 02:27:30  
> 分支: feature/hetero-optimization-v2  
> 责任 Agent: Antigravity (Google DeepMind)  

---

## 1. 目标与背景 (Motivation)

在多设备异构系统（Host CPU + 1× Phi 7120P + 3× NEC VE 1.0）中，不同硬件具有截然不同的算术强度与通信延迟特征：
- **Host CPU**：零数据搬运时延，低单核时钟延迟，适合小算子、控制逻辑、I/O 与统计汇总。
- **Intel Xeon Phi (KNC)**：244 线程高并发，适中内存带宽（157 GB/s），适合随机分支计算、高线程并行规约（如 Monte Carlo 路径生成）。配合常驻 Daemon，时延已压低至毫秒级。
- **NEC Vector Engine 1.0**：超强向量流处理器（VL=256）+ HBM2（实测 1,062 GB/s 单卡带宽），在计算密集型长向量/稠密矩阵乘（NLC DGEMM）和带宽密集型稀疏计算（SpMV）上具备绝对优势。

**优化目标**：
在 `src/scheduler/dispatcher.py` 中实现统一的自适应算子调度器 `AdaptiveDispatcher`：
1. **自动感知任务画像 (Workload Characterization)**：通过输入规模 $N$、算术强度（FLOP/Byte）或算子类型自动评估预期耗时。
2. **设备亲和与负载路由 (Intelligent Routing)**：
   - 数据规模小或启动开销 > 纯计算收益时：自动路由至 `host`；
   - 具有超高带宽或长向量稠密特征时：自动分发至空闲或负载最低的 `ve1/ve2/ve3`；
   - 强多线程/随机数/轻向量特征时：路由至 `phi0`（经常驻 Daemon）。
3. **与现有 TaskGraph 平滑联动**：支持 `TaskNode(auto_dispatch=True)`，无需开发者硬编码设备名字。
