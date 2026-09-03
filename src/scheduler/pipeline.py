"""
通用异步双缓冲流水线框架
pipeline.py — Phase 5: 生产-消费异步双缓冲 (Double Buffering)

核心特性:
- 生产者协程 (Producer): 负责数据生成、预处理、格式清洗 (通常运行在 Host CPU 或 Phi)
- 消费者协程 (Consumer): 负责计算、推理、向量求解 (通常并发派发给 3× VE)
- 双缓冲队列: 维持最大深度为 2 的流水线缓冲区，掩盖数据准备与 I/O 延迟
"""

import asyncio
import time
from typing import Callable, Any, Awaitable, List, Dict
from dataclasses import dataclass


@dataclass
class BatchItem:
    batch_id: int
    data: Any
    gen_time_sec: float = 0.0


class DoubleBufferedPipeline:
    """可复用的异步双缓冲流水线管理器"""

    def __init__(self, buffer_size: int = 2):
        self.buffer_size = buffer_size
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=buffer_size)
        self.results: List[Dict[str, Any]] = []

    async def run(
        self,
        total_batches: int,
        producer_fn: Callable[[int], Awaitable[Any]],
        consumer_fn: Callable[[BatchItem], Awaitable[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """执行双缓冲流水线
        
        Args:
            total_batches: 总批次数
            producer_fn: 异步生成函数 async def prod(batch_id) -> data。
                若生成是 CPU 密集，调用方需自己 `asyncio.to_thread`，否则会堵住事件循环、无法与 consumer 重叠。
            consumer_fn: 异步消费函数 async def cons(batch_item) -> dict
        """
        self.results.clear()

        async def _producer():
            for b_id in range(total_batches):
                t0 = time.time()
                data = await producer_fn(b_id)
                gen_time = time.time() - t0
                item = BatchItem(batch_id=b_id, data=data, gen_time_sec=gen_time)
                await self.queue.put(item)
            # 发送终止哨兵
            await self.queue.put(None)

        async def _consumer():
            while True:
                item = await self.queue.get()
                if item is None:
                    self.queue.task_done()
                    break
                t0 = time.time()
                res = await consumer_fn(item)
                proc_time = time.time() - t0
                res["batch_id"] = item.batch_id
                res["producer_elapsed"] = item.gen_time_sec
                res["consumer_elapsed"] = proc_time
                self.results.append(res)
                self.queue.task_done()

        # 并发启动流水线
        await asyncio.gather(_producer(), _consumer())
        return self.results
