# Phase 7.1 实施交付复盘: 自适应算子调度器 (Adaptive Dispatcher)

> 交付日期: 2026-09-03 02:28:30  
> 分支: feature/hetero-optimization-v2  
> 责任 Agent: Antigravity (Google DeepMind)  

---

## 1. 交付目标与架构提升

此前调度层任务的设备归属（如运行在 Host、Phi 还是 VE1/2/3）均由开发者手动硬编码（`"ve1"`, `"phi0"`）。
在遇到不同数据规模与复杂算法时，静态绑定无法发挥各硬件的最佳效能，甚至导致“小任务分派给 Phi 造成启动惩罚”的性能负向劣化。

**本次交付成果**：
1. **实现统一的自适应算子调度模块**：`src/scheduler/dispatcher.py`
   - 根据输入算子类型（DGEMM、SpMV、Monte Carlo、清洗生成等）与数据矩阵规模 $N$，结合 Roofline 算术强度模型实现全自动智能路由。
   - 小规模/控制型逻辑自动路由至 Host CPU。
   - 高并发线程/分支路径自动路由至卡内常驻的 Phi 7120P。
   - 稠密长向量与超高 HBM2 带宽计算自动多卡负载均衡至 3× NEC VE。
2. **深度无缝接入 TaskGraph 任务图引擎**：
   - `TaskNode` 默认开启 `device="auto"`。
   - 任务图在 `graph.add()` 拓扑装载阶段自动完成设备感知分派与动态功率预算补齐。
3. **测试套件扩容至 17 项全绿**：
   - 在 `tests/test_scheduler.py` 中新增 `test_adaptive_dispatcher`，覆盖 4 类路由场景。
   - 单元测试从 16 项增至 **17 项全部一次性 PASS**。
