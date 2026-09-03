# Uni — Intel Phi 7120P + NEC VE 1.0×3 异构计算协同项目

> 服务器: ASUS ESC4000 G4, 2× Xeon Gold 6252, Rocky Linux 8.10
> 加速卡: 1× Intel Xeon Phi 7120P (KNC) + 3× NEC Vector Engine 1.0

## 项目目标

在单台 ESC4000 G4 服务器上实现 Phi + VE 异构计算协同调度，最大化利用两种加速卡的互补计算特征。

## 算力概览

| 指标 | Phi 7120P | VE 1.0×3 | **合计** |
|------|----------|---------|---------|
| FP64 理论 | 1.21 TFLOPS | 6.48 TFLOPS | **7.69 TFLOPS** |
| FP64 可达成 | 0.58 TFLOPS | 5.25 TFLOPS | **5.83 TFLOPS** |
| 内存总量 | 16 GB GDDR5 | 144 GB HBM2 | **160 GB** |
| 内存带宽 | 157 GB/s | 3,186 GB/s | **3,343 GB/s** |

## 项目进度

| Phase | 内容 | 状态 | 说明 |
|-------|------|------|------|
| 0 | 硬件验证与基线确认 | ✅ | check_hw.sh 免密探测 |
| 1 | 统一软件栈搭建 (uv/ncc/ICC) | ✅ | 环境隔离 (uv + centos7-phi-dev 容器) |
| 2 | 核心调度层 (7 模块) | ✅ | 设备发现/NUMA/PowerCap/TaskGraph/Profiler |
| 3 | 协同基准测试 (TC-001~006) | ✅ | 4/6 通过, 5/6 标注 (5.68~5.76 TFLOPS) |
| 4 | 示例应用 (SpMV + 预处理 + MC) | ✅ | 端到端正确性校验 100% 通过 |
| 5 | 算力与流水线优化 (NLC + 双缓冲) | ✅ | NLC DGEMM 1750 GFLOPS; DoubleBufferedPipeline |
| 6 | Phi 启动时延攻坚 (常驻 Daemon) | ✅ | phi_worker_daemon 突破至 0.4ms 心跳时延 |
| 7 | 系统自适应与闭环安全 (调度大脑) | 🚀 7.1已交付 | AdaptiveDispatcher 自适应路由; 决策仅 2.15μs |

## 目录结构

```
uni/
├── README.md                      # 项目主说明
├── AGENTS.md                      # 开发者 Agent 声明与工作守则 (Antigravity)
├── docs/
│   ├── glossary.md                # 统一技术术语表 (KNC, VE, NLC, MPSS等)
│   ├── research/                  # 调研与基准性能测试记录
│   ├── plan/                      # 各阶段迭代设计方案
│   ├── impl/                      # 交付复盘与验收记录
│   └── architecture/              # 系统分层架构与拓扑规范
├── env/                           # Python 隔离虚拟环境 (uv 管理)
├── src/
│   ├── scheduler/                 # 智能异构调度层
│   │   ├── devices.py             # 设备发现 (Phi + 3×VE)
│   │   ├── phi.py / phi_client.py # Phi 管理 (ICC编译/常驻Daemon通信)
│   │   ├── ve.py                  # VE 管理 (ncc编译/NLC BLAS标准封装)
│   │   ├── numa.py                # NUMA 拓扑与双路亲和绑定
│   │   ├── power.py               # 1440W 安全功耗封顶与监控
│   │   ├── task_graph.py          # DAG 任务图 (支持 auto_dispatch)
│   │   ├── profiler.py            # Roofline 性能画像与实测对比
│   │   ├── pipeline.py            # 异步双缓冲流水线模板 (DoubleBuffering)
│   │   └── dispatcher.py          # 基于 Roofline 的自适应算子调度器
│   ├── kernels/{phi,ve}/          # 计算内核 (FMA/NLC DGEMM/MPI/Daemon)
│   ├── apps/
│   │   ├── hetero_spmv/           # 异构 SpMV (Phi分块+3VE并行乘法)
│   │   ├── hetero_dataprep/       # 数据预处理流水线
│   │   └── monte_carlo/           # Monte Carlo 亚式障碍期权定价
│   └── benchmarks/                # 基准测试封装
├── scripts/                       # 基准与硬件检查脚本 (TC-001~004, check_hw)
├── examples/                      # 示例 (basic/multi_task/pipeline/adaptive)
└── tests/                         # 自动化单元测试集 (17 项全绿)
```

## 文档索引

| 文档 | 内容 |
|------|------|
| `docs/glossary.md` | 异构系统与硬件核心专业术语表 |
| `docs/architecture/20260903_013621_system_architecture_spec.md` | Uni 系统分层架构设计与拓扑规范 |
| `docs/research/20260601_090918_heterogeneous_system_analysis.md` | 硬件规格、瓶颈识别、编程模型、协同模式 |
| `docs/research/20260603_bench_conclusions.md` | 全框架基准对比, 5条核心结论 |
| `docs/research/20260903_014900_performance_comparison.md` | 优化分支与主线版本性能对比分析报告 |
| `docs/research/20260903_023000_adaptive_dispatcher_benchmark.md` | 自适应调度器决策时延微基准与全框架性能报告 |
| `docs/plan/20260601_090918_development_roadmap.md` | Phase 0-4 分阶段规划路线图 |
| `docs/plan/20260903_014300_phase5_nlc_dgemm_integration.md` | Phase 5.1 NLC BLAS 矩阵库调度集成计划 |
| `docs/plan/20260903_014400_phase5_pipeline_template.md` | Phase 5.2 异步双缓冲流水线模板设计 |
| `docs/plan/20260903_015900_phase6_phi_daemon_plan.md` | Phase 6 Phi 常驻守护进程设计方案 |
| `docs/plan/20260903_022730_phase7_adaptive_dispatcher_plan.md` | Phase 7.1 自适应算子调度器设计方案 |
| `docs/impl/20260720_final_acceptance.md` | 终期验收报告 (Week 6 收尾 9/9 真实通过) |
| `docs/impl/20260903_014530_phase5_implementation.md` | Phase 5 交付记录 (NLC + 异步双缓冲) |
| `docs/impl/20260903_020500_phase6_phi_daemon_delivery.md` | Phase 6 交付复盘 (Phi 启动延迟压低至 0.4ms) |
| `docs/impl/20260903_022830_phase7_adaptive_dispatcher_delivery.md` | Phase 7.1 交付复盘 (自适应调度器与 TaskGraph 自动路由) |

## 快速开始

```bash
# 1. 硬件检查
bash scripts/check_hw.sh

# 2. 初始化 Python 环境 (uv, 不污染全局)
cd env && uv venv && source .venv/bin/activate && uv pip install numpy rich
cd ..

# 3. 运行基础验证
bash examples/basic/run.sh          # 四卡并行基线 (3,277 GFLOPS)

# 4. 运行基准测试
./env/.venv/bin/python3 scripts/bench_all.py       # 全框架统一基准
./env/.venv/bin/python3 scripts/bench_throughput.py # 数据中心吞吐 (5.68 TFLOPS)
./env/.venv/bin/python3 scripts/bench_pcie.py       # PCIe 带宽压力
./env/.venv/bin/python3 scripts/bench_mpi.py        # VE-MPI 扩展性

# 5. 运行示例应用
./env/.venv/bin/python3 src/apps/hetero_spmv/spmv_app.py        # 异构 SpMV
./env/.venv/bin/python3 src/apps/hetero_dataprep/dataprep_app.py # 数据预处理
./env/.venv/bin/python3 src/apps/monte_carlo/mc_app.py          # Monte Carlo 定价

# 6. 一键验收
bash scripts/run_all.sh 2>&1 | tee acceptance.log
```

## 基准测试结果摘要

| 测试 | 指标 | 结果 | 判定 |
|------|------|------|------|
| TC-001 PCIe 带宽 | 3VE 并发 H2D | 13.7 GB/s (效率 86%) | ⚠️ 标注 (文件路径限制) |
| TC-002 数据中心吞吐 | 4卡并行总算力 (N=2048) | **5.56 ~ 5.76 TFLOPS** | ✅ 超额达成 (≥5.0) |
| TC-003 流水线延迟 | 常驻 Daemon 任务时延 | **0.41 ms (0.00041s)** | ✅ 攻克 (原 2,000ms) |
| TC-004 VE-MPI 扩展性 | 3卡 Ring 效率 | **97.8%** (VE2调整后) | ✅ 优异 |
| TC-007 调度决策微基准 | 单次算子自适应路由 | **2.15 μs (46.4万次/秒)** | ✅ 零感知 CPU 延迟 |

## 调度层架构 (V2.0)

```
                    ┌──────────────────────────────────────────────┐
                    │               TaskGraph                      │  DAG 任务图
                    │  (auto_dispatch / 拓扑排序 / 异步并发控制)    │  自适应节点设备感知
                    └──────────────────────┬───────────────────────┘
                                           │
         ┌───────────────────┬─────────────┴───────┬───────────────────┐
         │                   │                     │                   │
  ┌──────┴──────────┐ ┌──────┴──────────┐   ┌──────┴──────────┐ ┌──────┴──────────┐
  │AdaptiveDispatcher│ │    NUMABinder   │   │    PowerCap     │ │ DoubleBuffered   │
  │ Roofline智能路由 │ │ 双路 NUMA 亲和  │   │ 1440W 安全功耗网│ │ Pipeline (双缓冲)│
  └──────┬──────────┘ └──────┬──────────┘   └──────┬──────────┘ └──────┬──────────┘
         │                   │                     │                   │
  ┌──────┴───────────────────┴─────────────────────┴───────────────────┴──────────┐
  │                               Runtime Layer                                   │
  │  PhiClient (0.4ms Daemon)       VERunner (NLC DGEMM 1.75T)       MPIRunner    │
  └───────────────────────────────────────────────────────────────────────────────┘
```

## 关键技术突破

1. **VE 向量算力全面释放**：调度层深度集成 NEC NLC 3.1.0，DGEMM 算力从 naive 的 64 GFLOPS 跃升至 **1,750 GFLOPS**（81% 极限达成率）。
2. **Phi 启动时延断崖式压缩**：自研卡内轻量常驻服务 `phi_worker_daemon.mic`，任务心跳往返由 **2.0 秒锐减至 0.4 毫秒**（提速近 5,000 倍）。
3. **自适应算子调度大脑**：实现 `AdaptiveDispatcher`，单次 Roofline 决策开销仅 **2.15 μs**，全自动进行 Host/Phi/VE 设备分配。
4. **异步双缓冲流水线**：实现 `DoubleBufferedPipeline`，支持计算批次与 I/O 准备批次深度重叠（Overlapping）。

