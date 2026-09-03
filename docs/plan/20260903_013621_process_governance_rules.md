# 工程管理与规范治理实施记录

> 记录时间: 2026-09-03 01:36:21  
> 责任 Agent: Antigravity (Google DeepMind)  
> 关联计划: guidelines_plan.md / optimization_plan.md  

---

## 1. 规范建设背景与落地动作

根据用户指导要求，本次对 Uni 项目工程规范、开发协议与技术文档管理机制进行了全面升级与固化：

1. **建立 docs 四分层与时间戳命名标准**：
   - 补充完善四大目录：`docs/research/`, `docs/plan/`, `docs/impl/`, `docs/architecture/`。
   - 今后任何中间过程与迭代方案文档，统一遵循 `YYYYMMDD_HHMMSS_<topic>.md` 格式。

2. **建立专有技术术语表**：
   - 落地 `docs/glossary.md`，对项目中涉及的体系结构（KNC, IMCI, SX-Aurora TSUBASA VE, HBM2）、驱动平台（MPSS, VEOS, micnativeloadex, ve_exec）、编译器与加速库（ICC 16.0, ncc/nfort, NLC 3.1.0）、算法调度模型（Roofline, SpMV, Double Buffering）进行系统性通俗定义与技术说明，后续交互持续增量补充。

3. **公示开发 Agent 身份与职责**：
   - 落地根目录 `AGENTS.md`，明确当前系统开发 Agent 标识为 `Antigravity`，明晰职责范围与五大执行准则（过程文档化、环境前置探测、环境隔离优先级、术语归档、提交前安全审计）。

4. **明确环境隔离与依赖安装优先级**：
   - `uv` 虚拟环境 > `conda` > `podman`/`docker` 容器。
   - 杜绝污染全局 Host 环境。

5. **确立动作前硬件状态判定门禁**：
   - 在触发耗时计算与编译前，自动验证 CPU、Phi、VE 加速卡与系统功耗预算。
