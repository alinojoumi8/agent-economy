import asyncio

from agents.runtime import AgentRuntime


class PipelineHarness:
    _decide_one = AgentRuntime._decide_one

    def __init__(self) -> None:
        self.decision_preparation_width = 1
        self.decision_pipeline_width = 2
        self._decision_pipeline_active = 0
        self._decision_pipeline_peak = 0
        self._decision_preparing = 0
        self._decision_preparing_peak = 0
        self.prepared: list[int] = []
        self.dispatched: list[int] = []
        self.dispatch_active = 0
        self.dispatch_peak = 0
        self.first_dispatch_started = asyncio.Event()
        self.dispatches_full = asyncio.Event()
        self.release_dispatch = asyncio.Event()

    def _prepare_decision(self, _tick: int, agent: int) -> int:
        self.prepared.append(agent)
        return agent

    async def _complete_prepared_decision(self, prepared: int) -> int:
        self.dispatched.append(prepared)
        self.dispatch_active += 1
        self.dispatch_peak = max(self.dispatch_peak, self.dispatch_active)
        if prepared == 1:
            self.first_dispatch_started.set()
        if self.dispatch_active == 2:
            self.dispatches_full.set()
        try:
            await self.release_dispatch.wait()
            return prepared
        finally:
            self.dispatch_active -= 1


def test_pipeline_prepares_the_next_agent_while_provider_is_waiting():
    async def scenario():
        harness = PipelineHarness()
        preparation_gate = asyncio.Semaphore(1)
        dispatch_gate = asyncio.Semaphore(1)
        pipeline_gate = asyncio.Semaphore(2)
        tasks = [
            asyncio.create_task(AgentRuntime._decide_pipelined_guarded(
                harness,
                7,
                agent,
                preparation_gate=preparation_gate,
                dispatch_gate=dispatch_gate,
                pipeline_gate=pipeline_gate,
            ))
            for agent in (1, 2)
        ]

        await asyncio.wait_for(harness.first_dispatch_started.wait(), timeout=1)
        for _ in range(20):
            if harness.prepared == [1, 2]:
                break
            await asyncio.sleep(0)

        assert harness.prepared == [1, 2]
        assert harness.dispatched == [1]
        assert harness._decision_pipeline_peak == 2

        harness.release_dispatch.set()
        assert await asyncio.gather(*tasks) == [1, 2]
        assert harness.dispatched == [1, 2]
        assert harness._decision_pipeline_active == 0
        assert harness._decision_preparing == 0

    asyncio.run(scenario())


def test_pipeline_is_bounded_and_preserves_dispatch_order():
    async def scenario():
        harness = PipelineHarness()
        harness.decision_preparation_width = 2
        harness.decision_pipeline_width = 3
        preparation_gate = asyncio.Semaphore(2)
        dispatch_gate = asyncio.Semaphore(2)
        pipeline_gate = asyncio.Semaphore(3)
        tasks = [
            asyncio.create_task(AgentRuntime._decide_pipelined_guarded(
                harness,
                8,
                agent,
                preparation_gate=preparation_gate,
                dispatch_gate=dispatch_gate,
                pipeline_gate=pipeline_gate,
            ))
            for agent in range(1, 9)
        ]

        await asyncio.wait_for(harness.dispatches_full.wait(), timeout=1)
        for _ in range(20):
            if len(harness.prepared) == 3:
                break
            await asyncio.sleep(0)

        assert harness.prepared == [1, 2, 3]
        assert harness.dispatched == [1, 2]
        assert harness._decision_pipeline_peak == 3
        assert harness.dispatch_peak == 2

        harness.release_dispatch.set()
        assert await asyncio.gather(*tasks) == list(range(1, 9))
        assert harness.dispatched == list(range(1, 9))
        assert harness.dispatch_peak == 2
        assert AgentRuntime.decision_pipeline_status(harness) == {
            "preparation_width": 2,
            "pipeline_width": 3,
            "active": 0,
            "peak_active": 3,
            "preparing": 0,
            "peak_preparing": 1,
        }

    asyncio.run(scenario())
