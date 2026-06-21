"""Rate-limit exception raised by AgentLauncher implementations.

When the external agent process exits because the API is rate-limited
or overloaded, launchers raise ``RateLimitError`` instead of emitting
``session.error``.  The dispatcher catches this specifically and drives
the exponential-backoff retry loop (issue #62) rather than marking the
task terminal immediately.

``captured_id`` carries the conversation ID extracted from the process
stdout before it exited (from ``system/api_retry`` events in
stream-json mode), allowing the next attempt to resume the conversation.
``None`` means no ID was captured; the retry starts a fresh conversation
and emits ``agent.conversation_resume_skipped``.
"""

from __future__ import annotations


class RateLimitError(Exception):
    """Raised by a launcher when the agent exits due to API rate-limiting.

    Attributes
    ----------
    captured_id:
        Conversation ID captured before the process exited, or ``None``.
    reason:
        The ``error`` field from the CLI's ``system/api_retry`` event
        (e.g. ``"rate_limit"``, ``"overloaded"``), or a synthetic string
        derived from stderr pattern matching for providers that lack
        structured retry events.
    """

    def __init__(self, captured_id: str | None, reason: str) -> None:
        super().__init__(f"rate limit: {reason} (conversation_id={captured_id!r})")
        self.captured_id = captured_id
        self.reason = reason
