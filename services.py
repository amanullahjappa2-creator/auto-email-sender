"""Typed application services exposed to Flask blueprints."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MailFlowServices:
    """Blueprint-facing service surface.

    The callables are intentionally typed as flexible adapters because the
    existing application functions are also public compatibility hooks used by
    the scheduler and tests.
    """

    ensure_sample_templates_for_user: Callable[..., Any]
    save_template: Callable[..., Any]
    send_admin_verification_code: Callable[..., Any]
    send_compose_emails: Callable[..., Any]
    user_templates: Callable[..., Any]
    admin_code_digest: Callable[..., Any]
