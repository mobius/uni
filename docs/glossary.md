# Uni 异构计算项目术语表 (Glossary)

本文档记录项目中涉及的硬件架构、驱动栈、软件库、编程模型以及交互过程中出现的专业技术词汇与释义。

---

## 1. 硬件架构与规格 (Hardware Architecture)

### KNC (Knights Corner)
- **定义**：Intel 第一代 Xeon Phi 协处理器架构代号（如本项目的 Xeon Phi 7120P）。
- **说明**：基于 22nm 制程，拥有 61 个由初代奔腾 P54C 改进而来的 x86 顺序核心，支持 4-way 超线程（共 244 线程）与 512 位宽的宽向量扩展指令集（IMCI/KNC-VPU），搭载 16GB GDDR5 显存。采用被动散热设计，必须严格监控工作温度。

### IMCI (Initial Many Core Instructions)
- **定义**：Knights Corner (KNC) 专属的 512-bit SIMD 指令集架构，前身由 Larrabee 项目发展而来。
- **说明**：支持 32 个 512 位向量寄存器与 FMA（乘累加），与主流的 Intel AVX-512 不二进制兼容，必须使用特定的编译器（如 ICC with `-mmic`）进行交叉编译。

### SX-Aurora TSUBASA / VE (Vector Engine)
- **定义**：日本电气（NEC）推出的 PCI-e 向量计算卡。本项目使用的是 VE 1.0 (Type 10BE-P / 10B-P)。
- **说明**：单卡包含 8 个超强向量核心（每个核心含 3 个向量流水线），配有 48GB HBM2 堆叠高带宽内存，单卡理论内存带宽达 1.35 TB/s，FP64 双精度理论峰值 2.16 TFLOPS。

### HBM2 (High Bandwidth Memory 2)
- **定义**：第二代高带宽内存。
- **说明**：通过 TSV（硅通孔）技术垂直堆叠 DRAM 芯片，提供比传统 GDDR/DDR 高出一个数量级的访存带宽。在 VE 1.0 上实测带宽超过 1,000 GB/s，是内存受限型（Memory-bound）算子的理想加速介质。

### NUMA (Non-Uniform Memory Access)
- **定义**：非统一内存访问架构。
- **说明**：双路服务器（2× Xeon Gold 6252）具有两个独立 NUMA 节点。不同 PCIe 插槽直连特定的 CPU Socket，调度时须通过 `numactl` 绑定进程至对应的 NUMA 节点，避免跨 Socket 远端互联总线（UPI）通信导致带宽衰减和延迟增加。

---

## 2. 驱动与底层系统栈 (Driver & System Stacks)

### MPSS (Manycore Platform Software Stack)
- **定义**：Intel Xeon Phi (KNC) 的专用驱动和软件栈，本项目采用版本 3.8.6。
- **说明**：包含内核驱动、mic0 虚拟网络网卡驱动、文件系统镜像加载器及主机控制实用程序（如 `micinfo`, `micctrl`）。

### VEOS (Vector Engine Operating System)
- **定义**：NEC Vector Engine 的轻量级虚拟操作系统抽象层，本项目采用版本 3.6.1。
- **说明**：VEOS 将 Host Linux 内核系统调用透明代理至 VE 硬件中，使得 VE 能够直接透明访问主机的文件系统和部分网络资源。

### micnativeloadex
- **定义**：Intel MPSS 提供的原生二进制加载与执行工具。
- **说明**：用于将 Host 侧交叉编译出的 `.mic` 可执行程序和依赖库动态分发加载至卡内 Linux 环境并启动执行。由于包含全套 ELF 解析、环境设置，每次单独调用有 ~1.8-2.5s 的固有启动开销。

### ve_exec
- **定义**：NEC VEOS 提供的向量程序启动命令。
- **说明**：通过 `ve_exec -N <node_id> ./bin` 直接在指定的 VE 节点运行向量化编译生成的可执行文件，天然具备主机文件系统穿透访问能力。

---

## 3. 编译器与高性能库 (Compilers & Libraries)

### ICC (Intel C/C++ Compiler 16.0)
- **定义**：Intel 经典编译器（Classic Compiler）。
- **说明**：支持 `-mmic` 目标架构编译。现代高版本 GCC/Clang 及 ICC 已放弃对 KNC 架构的支持，因此本项目通过 Podman 隔离容器（`centos7-phi-dev`）维护 ICC 16.0，避免污染 Host 环境。

### ncc / nfort
- **定义**：NEC 为 SX-Aurora TSUBASA 开发的专用 C/C++ 与 Fortran 向量编译器。
- **说明**：支持自动向量化编译（Automatic Vectorization），能够将标准循环高效展开为 VE 的长向量指令（Vector Length up to 256 elements）。

### NLC (NEC Numeric Library Collection)
- **定义**：NEC 为 VE 定制的超高性能数值计算数学库集合（类似 Intel MKL）。
- **说明**：包含高性能 BLAS、LAPACK、FFT 等核心算法库。本项目中通过链接 NLC 3.1.0 的 `cblas_dgemm`，使单卡 DGEMM 从 Naive 循环的 64 GFLOPS 跃升至 1,750 GFLOPS。

---

## 4. 调度与算法模型 (Scheduling & Computational Concepts)

### Roofline Model (屋顶模型)
- **定义**：一种直观的性能评估模型，刻画计算密集度（Operational Intensity, FLOP/byte）与硬件理论峰值算力、内存带宽之间的约束关系。
- **说明**：用于分析算子是处于“内存带宽受限区”（Memory-bound）还是“计算峰值受限区”（Compute-bound），本项目 Profiler 模块依据 Roofline 模型对异构任务进行智能设备分派决策。

### SpMV (Sparse Matrix-Vector Multiplication)
- **定义**：稀疏矩阵与密集向量的乘法运算。
- **说明**：广泛应用于图计算、科学仿真和迭代求解。本项目采用异构协同策略：由具有高并发多线程特性的 Phi 负责 CSR（Compressed Sparse Row）数据分块清洗，由具备超高 HBM 带宽的 VE 并行执行向量乘。

### Double Buffering (流水线双缓冲)
- **定义**：一种将 I/O 传输与计算重叠重合（Overlapping）的优化机制。
- **说明**：通过两块交替使用的内存缓冲区，在加速卡计算当前批次数据（Buffer A）的同时，后台异步读取或传输下一批次数据（Buffer B），有效掩盖通信和 PCIe 数据搬运延迟。

### Adaptive Dispatcher (自适应调度器)
- **定义**：按算子名与数据规模把任务分到 Host / Phi / VE 的启发式路由组件。
- **说明**：`scheduler.dispatcher` 在 feature 分支引入。单次 `dispatch()` 约 2 μs。预估数字来自 Profiler 查表，当前实现不做完整 Roofline 强度求解。

### Phi Worker Daemon (Phi 常驻守护进程)
- **定义**：驻留在 Xeon Phi 卡内、经虚拟网口接任务的常驻进程。
- **说明**：避免每次 `micnativeloadex` 重新装载。预热后 PING 约 0.4–1 ms。OP_STATS 对 N=512 矩阵往返约 20 ms（含载荷），TC-003 增量 overhead 约 7%。
