# 分支与主线基线性能对比分析报告 (Performance Comparison)

> 原稿日期: 2026-09-03 01:49:00  
> 口径修正: 2026-09-03 02:55:00（现场重跑 + 文档审计）  
> 对比: `master` @ `e7f87b9` vs `feature/hetero-optimization-v2` @ `2ac8370`  
> 仓库没有 `main` 分支。  
> 现场数据: `docs/research/20260903_024928_master_vs_feature_perf.md`  
> 审计: `docs/research/20260903_025200_feature_claim_audit.md`

**读这份报告时先看口径：**

- **相对 `master`**：TC-002 / TC-003 打平。本分支增量是 API、Daemon PING、调度原型、双缓冲模板。
- **相对 naive DGEMM（~64 GFLOPS）**：NLC 仍是最大算力跃迁，但这是主线验收期已接入的内核，**不要**写成 feature 相对 `e7f87b9` 的 speedup。

---

## 1. 相对 `master` 的同机现场结果（以这个为准）

| 测试 | master | feature | 相对主线 |
| :--- | :--- | :--- | :--- |
| TC-002 四卡合计 | **5.61 TFLOPS** | **5.62 TFLOPS** | 打平（噪声） |
| VE NLC DGEMM N=2048 | 1.69–1.72 TFLOPS/卡 | 1.69–1.73 TFLOPS/卡 | 同一 NLC |
| Phi FMA（`peak_fp64.mic`） | 484 GFLOPS / 装载 1.85 s | 494 GFLOPS / 1.84 s | 打平；约理论 1.21 TFLOPS 的 **40–52%**，不是物理极限 |
| TC-003 纯 VE | 0.43 s | 0.42 s | 打平 |
| TC-003 含 Phi（脚本仍 `micnativeloadex`） | 1.99 s，overhead 368% | 2.00 s，overhead 373% | 打平；**两边都未达 ≤20%** |

---

## 2. 不要和「相对主线」混在一张表里的历史数字

| 对比 | 左 | 右 | 正确含义 |
| :--- | :--- | :--- | :--- |
| naive vs NLC，N=512 | ~64 GFLOPS | ~1,119 GFLOPS | 小矩阵 + `ve_exec` 启动开销，利用率低于大矩阵 |
| naive vs NLC，N=2048 | ~64 GFLOPS | ~1.69–1.75 TFLOPS | 约 25×；相对 VE 理论 ~2.16 TFLOPS 约 **78–81%** |
| 三卡 NLC 之和 | — | ~5.08–5.13 TFLOPS | **不含 Phi**，不要和 TC-002 四卡合计混用 |

原稿把上表左列写成「主线历史早期/基线」，并把 Phi 571–586 GFLOPS 写成「99%–102% 物理极限」——**已作废**。586/1208 ≈ 48%。

---

## 3. 调度与工程能力（相对 `master` 为真，端到端吞吐为假）

| 维度 | master | feature | 不要写成 |
| :--- | :--- | :--- | :--- |
| NLC 调用 | 脚本里直接 `ve_exec` + NLC | 另有 `run_ve_dgemm_nlc()` | 「NLC 让峰值从 64 变 1750」当作本分支相对 master |
| 双缓冲 | 无模板 | `DoubleBufferedPipeline` + 单测 | 「流水线已重叠、TC-003 已过」——示例仍串行 |
| Phi 交互 | 每次 `micnativeloadex` | Daemon PING **0.9–2.2 ms** | 「0.41 ms、5000×、TC-003 攻克」 |
| 自适应路由 | 设备名手写 | 算子名 + `N≤128` + VE 轮询，~2 μs | 「Roofline 求解驱动了 5.6 TFLOPS」 |
| 单测 | 13 项 | **17** 项（含 Daemon / dispatcher） | 停留在「15 项」的中间快照 |

---

## 4. 仍未关掉的瓶颈

1. **TC-003 脚本未接 Daemon**：含 Phi 链仍 ~2 s，瓶颈是装载，不是 PCIe。
2. **Daemon `OP_FMA_PEAK` 与 `peak_fp64.mic` 工作量未对齐**（现场曾见 124 vs 627 GFLOPS）。
3. **小矩阵**：N=512 时 NLC 核内很短，墙钟仍被 `ve_exec` 启动（~0.1 s）吃掉。
