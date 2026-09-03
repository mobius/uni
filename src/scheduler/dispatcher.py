"""
自适应算子调度器 (Adaptive Dispatcher)
dispatcher.py — Phase 7: 基于 Roofline 模型与设备特征的智能算子分发

核心逻辑:
- 小规模 / 低强度 / 控制型任务 (N <= 128 或 op in {"gen", "stats", "reduce_scalar"}) -> 路由至 host
- 长向量 / 高内存带宽 / 稠密浮点计算 (op in {"dgemm", "spmv_vec", "fma_vector", "fft"}) -> 负载均衡分派至 VE1/VE2/VE3
- 高线程并发 / 随机路径生成 / 独立分支轻向量 (op in {"monte_carlo_path", "csr_partition", "random_walk"}) -> 路由至 phi0
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from .profiler import Profiler, DEVICE_MODELS
from .devices import discover_all


@dataclass
class DispatchDecision:
    target_device: str          # "host", "phi0", "ve1", "ve2", "ve3"
    reason: str                 # 决策缘由 (如 "memory_bound_hbm", "host_small_scale")
    estimated_gflops: float
    estimated_sec: float


class AdaptiveDispatcher:
    """基于硬件微架构与 Roofline 画像的自适应设备调度器"""

    def __init__(self, profiler: Optional[Profiler] = None):
        self.profiler = profiler or Profiler()
        self._ve_round_robin = 0
        self._available_ves = ["ve1", "ve2", "ve3"]

    def dispatch(self, op: str, N: int = 512, **kwargs) -> DispatchDecision:
        """根据操作算子类型和数据规模进行自适应设备分派
        
        Args:
            op: 算子名称 (dgemm, spmv, fma, gen, stats, mc_path, etc.)
            N: 数据规模 / 矩阵阶数 / 元素点数
            kwargs: 扩展参数 (如 use_nlc, density 等)
        """
        # 1. 规整化算子类型
        op_lower = op.lower()

        # 2. 小数据规模或控制/统计逻辑，直接调度给 Host CPU (避免任何加速卡交互开销)
        if op_lower in ("gen", "stats", "report", "aggregate_scalar") or N <= 128:
            est = self.profiler.estimate("host", op_lower if op_lower in ("gen", "stats") else "dgemm", N=N)
            return DispatchDecision(
                target_device="host",
                reason=f"small_scale_or_control (N={N})",
                estimated_gflops=est.est_gflops,
                estimated_sec=est.est_time_s,
            )

        # 3. 适合 Intel Xeon Phi 的高并发线程任务
        if op_lower in ("mc_path", "monte_carlo", "csr_partition", "random_walk", "branching_heavy"):
            est = self.profiler.estimate("phi", "fma_peak", N=N)
            return DispatchDecision(
                target_device="phi0",
                reason="many_thread_concurrency_244_threads",
                estimated_gflops=est.est_gflops,
                estimated_sec=est.est_time_s,
            )

        # 4. 适合 NEC Vector Engine 的长向量 / 稠密 / 超高 HBM 带宽任务
        if op_lower in ("dgemm", "matmul", "spmv", "fma", "fma_peak", "scale", "transpose", "aggregate"):
            target_ve = self._get_next_ve()
            use_nlc = kwargs.get("use_nlc", True)
            est = self.profiler.estimate("ve", "dgemm" if "dgemm" in op_lower or "matmul" in op_lower else "fma_peak", N=N, use_nlc=use_nlc)
            return DispatchDecision(
                target_device=target_ve,
                reason="vector_execution_and_hbm2_bandwidth",
                estimated_gflops=est.est_gflops,
                estimated_sec=est.est_time_s,
            )

        # 5. 默认回退保底：分发给当前轮询的 VE
        target_ve = self._get_next_ve()
        return DispatchDecision(
            target_device=target_ve,
            reason="default_fallback_to_ve",
            estimated_gflops=100.0,
            estimated_sec=0.1,
        )

    def _get_next_ve(self) -> str:
        """多卡轮询均衡负载"""
        ve = self._available_ves[self._ve_round_robin % len(self._available_ves)]
        self._ve_round_robin += 1
        return ve


# 全局单例
_dispatcher_instance: Optional[AdaptiveDispatcher] = None

def get_dispatcher() -> AdaptiveDispatcher:
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = AdaptiveDispatcher()
    return _dispatcher_instance
