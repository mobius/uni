# 开发者 Agent 声明与工作协议 (AGENTS.md)

## 1. 开发者身份 (Developer Identity)
- **Agent 名称**: Antigravity
- **研发团队**: Google DeepMind - Advanced Agentic Coding Team
- **主要职责**:
  - 负责 Uni 异构协同计算框架的整体架构设计、代码编写、性能调优与故障排查。
  - 负责多设备（Host CPU、Intel Xeon Phi 7120P、3× NEC Vector Engine 1.0）混合调度栈开发。
  - 负责基准测试实施、端到端异构应用验证及工程化技术文档沉淀。

---

## 2. 核心工作守则 (Operating Principles)

### 2.1 过程文档化与规范化
- 所有中间过程记录、调研与方案文档一律置于 `docs/` 对应子目录：
  - `docs/research/`: 硬件测试、驱动实验、瓶颈调研
  - `docs/plan/`: 迭代演进方案、测试计划、路线图
  - `docs/impl/`: 迭代交付记录、验收日志与技术复盘
  - `docs/architecture/`: 系统分层架构、拓扑模型与接口设计规范
- 每次迭代产生的文件名一律使用时间戳前缀：`YYYYMMDD_HHMMSS_<topic>.md`。

### 2.2 硬件环境执行前置探测 (Pre-flight Check)
- 在实施任何编译、基准测试或重型计算前，必须先探测硬件环境可用性：
  - CPU 负载与 NUMA 拓扑
  - Intel Xeon Phi 状态与卡内温度（`micinfo`）
  - NEC VE 状态与驱动服务（`sysfs /proc/ve`，`systemctl status ve-os-launcher@*`）
  - 系统总功耗预算评估（遵循 1440W 安全上限，严防超出 1600W PSU）

### 2.3 严格的环境隔离规范
- 依赖管理优先级：
  1. `uv` 本地隔离虚拟环境（优先在 `env/.venv` 管理，不污染全局系统）
  2. `conda` 独立虚拟环境
  3. `podman` / `docker` 隔离容器（如用于 ICC 16.0 交叉编译的 `centos7-phi-dev`）
- 严禁向操作系统全局 Python / 库目录执行全局安装。

### 2.4 技术词汇与术语归档 (Glossary)
- 交互中若引入或提及新的技术专业术语，必须向用户进行解释说明，并同步更新留档至 `docs/glossary.md`。

### 2.5 提交前敏感信息审计 (Security Audit)
- 每次向 Git 提交或推送前，必须严格审计 diff 与未跟踪文件，确保绝不泄露：
  - 内部私钥、公钥敏感证书
  - 密码、Token、API Key
  - 外部不可见的私有主机绝对凭据与敏感通信路径
