# Phase 6 实施计划: Intel Xeon Phi 常驻守护进程 (Resident Worker Daemon)

> 日期: 2026-09-03 01:59:00  
> 分支: feature/hetero-optimization-v2  
> 责任 Agent: Antigravity  

---

## 1. 目标与背景 (Motivation)

- **现状痛点**：当前 Phi 7120P 执行任务必须经过 `micnativeloadex` 和 `scp`，导致哪怕是 0.01 秒的极轻量计算，也有高达 **1.8s ~ 2.5s** 的固定时延惩罚，无法参与细粒度流式计算。
- **目标**：在卡内部署轻量常驻 C 服务 `phi_worker_daemon.mic`，监听指定端口（如 19800）。Host 调度层维护 TCP 长连接池，实现**指令与数据的纯内存流分发**，将分发时延从 2 秒降低到毫秒级（<20ms）。

---

## 2. 协议与架构设计 (Architecture & Protocol)

```
Host (Python Scheduler)                      Intel Xeon Phi (KNC / BusyBox)
  │                                                      │
  │─── 1. 初始化: 一次性启动 daemon (后台) ─────────────>│ (phi_worker_daemon.mic)
  │─── 2. TCP 连接: 172.31.1.1:19800 ──────────────────>│ 监听并建立持久连接
  │                                                      │
  │─── 3. 发送 Task Request (Magic, Opcode, Length) ────>│ 解析请求并在 244 线程
  │─── 4. 发送 Payload (Data Buffer) ───────────────────>│ 上执行 FMA/清洗/运算
  │                                                      │
  │<── 5. 回传 Task Response (Status, GFLOPS, ResData) ──│ 完成计算立即回传
```

### 协议头定义 (Binary Header 32-byte)
- `magic`: 0x50484930 (`PHI0`)
- `opcode`: 1=PING, 2=FMA_PEAK, 3=DATA_CLEAN, 99=SHUTDOWN
- `payload_len`: 数据载荷字节数
- `reserved`: 对齐预留

---

## 3. 实施步骤

1. **编写卡内 C 守护进程源码**：`src/kernels/phi/phi_worker_daemon.c`
2. **在 Podman 容器 (centos7-phi-dev) 中交叉编译**：输出 `phi_worker_daemon.mic`
3. **在调度层封装客户端管理模块**：`src/scheduler/phi_client.py`，管理 Daemon 启停与请求派发
4. **单元测试与回归**：新增 `tests/test_phi_daemon.py`
