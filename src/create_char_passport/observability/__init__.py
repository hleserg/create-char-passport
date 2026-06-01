"""Observability: Sentry initialization and component tagging."""

from create_char_passport.observability.sentry import init_sentry, tag_component

__all__ = ["init_sentry", "tag_component"]
