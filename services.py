"""Typed application services exposed to Flask blueprints."""

from dataclasses import dataclass
from typing import Any, Callable, Sequence


DeliveryResult = tuple[str, str]
Attachment = tuple[str, bytes, str, str]


@dataclass(frozen=True)
class MailFlowServices:
    """Blueprint-facing service surface.

    The callables retain the public application functions' real route-facing
    signatures, while the application keeps compatibility wrappers for tests
    and the scheduler.
    """

    ensure_sample_templates_for_user: Callable[[int], list[Any]]
    save_template: Callable[[str, str, str], tuple[Any, bool]]
    send_admin_verification_code: Callable[[Any, str, str], None]
    send_compose_emails: Callable[
        [int, Sequence[str], str, str], list[DeliveryResult]
    ]
    user_templates: Callable[[], list[Any]]
    admin_code_digest: Callable[[int, str, str], str]
