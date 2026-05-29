"""Kernel sidechain state management.

Kernel planner steps are stored in a separate sidechain, NOT in the main chat log.
This prevents kernel step progress from polluting the main conversation context.

Only the final answer is written to the main chat log.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)

@dataclass
class KernelStep:
    index: int
    kind: str
    title: str
    explanation: str
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    expected_output: str = ""
    status: str = "pending"
    observation: str = ""
    fingerprint: str = ""


@dataclass
class KernelSidechain:
    """Sidechain state for kernel planner execution.
    
    This is separate from the main chat log to avoid context pollution.
    """
    conversation_id: str
    user_text: str
    steps: list[KernelStep] = field(default_factory=list)
    is_active: bool = True
    
    def add_step(
        self,
        *,
        index: int,
        kind: str,
        title: str,
        explanation: str,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        expected_output: str = "",
        fingerprint: str = "",
    ) -> KernelStep:
        """Add a new step to the sidechain."""
        step = KernelStep(
            index=index,
            kind=kind,
            title=title,
            explanation=explanation,
            tool_name=tool_name,
            tool_args=tool_args or {},
            expected_output=expected_output,
            fingerprint=fingerprint,
        )
        self.steps.append(step)
        LOGGER.debug(
            "Kernel sidechain step added: index=%d kind=%s tool=%s",
            index, kind, tool_name,
        )
        return step
    
    def finalize_step(
        self,
        *,
        success: bool,
        observation: str,
    ) -> None:
        """Finalize the last step with result."""
        if not self.steps:
            return
        step = self.steps[-1]
        step.status = "done" if success else "failed"
        step.observation = observation
        LOGGER.debug(
            "Kernel sidechain step finalized: index=%d status=%s",
            step.index, step.status,
        )
    
    def get_completed_steps_summary(self) -> list[dict[str, Any]]:
        """Get summary of completed steps for final answer rendering."""
        return [
            {
                "index": step.index,
                "kind": step.kind,
                "title": step.title,
                "tool_name": step.tool_name,
                "status": step.status,
                "observation": step.observation,
                "fingerprint": step.fingerprint,
            }
            for step in self.steps
        ]
    
    def close(self) -> None:
        """Mark sidechain as inactive."""
        self.is_active = False
        LOGGER.debug(
            "Kernel sidechain closed: conversation_id=%s steps=%d",
            self.conversation_id, len(self.steps),
        )


_current_kernel_sidechain: ContextVar[KernelSidechain | None] = ContextVar(
    "current_kernel_sidechain", default=None
)


def get_current_kernel_sidechain() -> KernelSidechain | None:
    """Get the current kernel sidechain, if any."""
    return _current_kernel_sidechain.get()


def create_kernel_sidechain(
    conversation_id: str,
    user_text: str,
) -> KernelSidechain:
    """Create a new kernel sidechain for the current context."""
    sidechain = KernelSidechain(
        conversation_id=conversation_id,
        user_text=user_text,
    )
    _current_kernel_sidechain.set(sidechain)
    LOGGER.debug(
        "Kernel sidechain created: conversation_id=%s",
        conversation_id,
    )
    return sidechain


def close_kernel_sidechain() -> KernelSidechain | None:
    """Close and return the current kernel sidechain."""
    sidechain = _current_kernel_sidechain.get()
    if sidechain:
        sidechain.close()
        _current_kernel_sidechain.set(None)
    return sidechain
