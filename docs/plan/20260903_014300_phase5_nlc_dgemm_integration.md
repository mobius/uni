# Phase 5.1 实施计划: NEC NLC BLAS 全面集成与算力跃升

> 日期: 2026-09-03 01:43:00  
> 分支: feature/hetero-optimization-v2  
> 责任 Agent: Antigravity  

---

## 1. 目标与背景

在现有的 `src/scheduler/ve.py` 中，仅支持编译运行简单的 `peak_fp64.c` 内核，尚未将具备 1750 GFLOPS（81% 峰值）能力的 `dgemm_nlc.c` 作为标准计算算子集成到 `ve.py` 的 API 中。
同时，调度层缺乏直接调用 NLC DGEMM 的标准入口，导致应用层需要手动编写 shell 拼接参数。

**本阶段目标**：
1. 在 `src/scheduler/ve.py` 中实现标准化的 NLC DGEMM 编译与执行接口：`compile_ve_dgemm_nlc()` 与 `run_ve_dgemm_nlc(ve_id, input_path, output_path, ...)`。
2. 支持自动配置 `VE_LD_LIBRARY_PATH=/opt/nec/ve/nlc/3.1.0/lib` 与 `numactl` 绑定。
3. 扩展单元测试 `tests/test_scheduler.py`，新增 NLC 模块导出与功能测试。
4. 保证测试套件持续通过（从 13 项扩展至 14 项全部通过）。
