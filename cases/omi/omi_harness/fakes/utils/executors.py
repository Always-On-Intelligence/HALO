"""Fake of backend/utils/executors.py: the thread pools run work inline, in submission order.

Upstream submits post-persistence work (vector upsert, action items, webhooks) to background
pools. Running it inline makes each run deterministic; the order of side effects is unchanged.
"""
import asyncio
from concurrent.futures import Future


class InlineExecutor:
    def __init__(self, name):
        self.name = name

    def submit(self, fn, *args, **kwargs):
        f = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as e:   # surfaced through the future, as with a pool
            f.set_exception(e)
        return f

    def shutdown(self, wait=True):
        return None


critical_executor = InlineExecutor('critical')
db_executor = InlineExecutor('db')
llm_executor = InlineExecutor('llm')
stripe_executor = InlineExecutor('stripe')
sync_executor = InlineExecutor('sync')
postprocess_executor = InlineExecutor('postprocess')
cleanup_executor = InlineExecutor('cleanup')
storage_executor = InlineExecutor('storage')
speaker_tag_verify_executor = InlineExecutor('speaker_tag_verify')
cimd_executor = InlineExecutor('cimd')


class ExecutorSaturatedError(RuntimeError):
    pass


def get_jev_shadow_executor():
    return InlineExecutor('jev_shadow')


async def run_blocking(executor, fn, *args, **kwargs):
    return fn(*args, **kwargs)


def submit_with_context(executor, fn, *args, **kwargs):
    f = executor.submit(fn, *args, **kwargs)
    error = f.exception()
    if error is not None:
        import logging
        # task sync to external task apps and outgoing webhooks are inert stubs here; anything else is logged
        benign = 'a coroutine was expected, got <stub' in str(error)
        logging.getLogger(__name__).log(logging.DEBUG if benign else logging.ERROR, 'background task failed: %r', error)
    return f


def start_background_task(coro, *, name: str = ''):
    return asyncio.ensure_future(coro)


def get_executor_metrics():
    return []


def get_background_task_count() -> int:
    return 0


async def drain_background_tasks(timeout: float = 10.0) -> int:
    return 0


def shutdown_executors():
    return None
