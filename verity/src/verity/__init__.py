"""PremiumIQ Verity — AI Trust & Compliance Framework."""

import logging

from verity.core.client import Verity

__all__ = ["Verity"]
__version__ = "0.1.0"

# SDK safety: NullHandler prevents "No handlers could be found" warnings
# when Verity is used as a library without the consuming app configuring logging.
logging.getLogger("verity").addHandler(logging.NullHandler())
