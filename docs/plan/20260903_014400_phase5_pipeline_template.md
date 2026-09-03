# Phase 5.2 实施计划: 可复用异步双缓冲流水线模板 (Async Double Buffering)

> 日期: 2026-09-03 01:44:00  
> 分支: feature/hetero-optimization-v2  
> 责任 Agent: Antigravity  

---

## 1. 目标与背景

在异构应用中，通常包含：
- 阶段 1：Host 或 Phi 进行数据生成 / 清洗 / 分块预处理。
- 阶段 2：数据中转与传输（PCIe DMA 或网络文件穿透）。
- 阶段 3：3× VE 并行执行高性能数值计算（如 NLC DGEMM 或 SpMV）。

传统的流水线是串行等待：即必须等全部数据预处理并落盘完成后，再开始加速卡计算。
**优化目标**：
在 `src/scheduler/pipeline.py` 中构建通用的 `DoubleBufferedPipeline` 类：
- 维护双缓冲槽（Slot A / Slot B）。
- 启动 Producer（数据生成/预处理协程）与 Consumer（加速卡执行协程）并发执行。
- 在 VE 计算批次 $K$ 的同时，Host 异步预处理并装填批次 $K+1$，通过 `asyncio.Queue` 与信号量实现重叠，消除空转时间。
