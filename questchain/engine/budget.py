"""Finite dispatch accounting shared by a root run and its delegated agents."""

from threading import Lock


class ToolBudgetExceeded(RuntimeError):
    """No further tool dispatches may start in this run."""


def validate_tool_call_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 10_000:
        raise ValueError("QUESTCHAIN_MAX_TOOL_CALLS must be an integer from 1 to 10000.")
    return value


class ToolCallBudget:
    """Count attempts before dispatch; failures/cancellation never refund capacity.

    No await occurs during reservation. The lock also protects explicit sharing
    across threads. This is an application guard, not a sandbox for custom code.
    """

    def __init__(self, limit: int):
        self.limit = validate_tool_call_limit(limit)
        self._used = 0
        self._lock = Lock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    def reserve(self) -> None:
        with self._lock:
            if self._used >= self.limit:
                raise ToolBudgetExceeded(
                    f"Aggregate tool-call budget exhausted ({self.limit} attempts). "
                    "The rejected tool was not started. Review completed work before an explicit retry."
                )
            self._used += 1


def new_tool_budget() -> ToolCallBudget:
    from questchain.config import MAX_TOOL_CALLS

    return ToolCallBudget(MAX_TOOL_CALLS)
