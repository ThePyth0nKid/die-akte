# SPDX-License-Identifier: MIT
"""Client, CLI und gemeinsame Arbeitsschritte für die API einer Akte."""

from .client import Akte, AkteFehler, AkteNichtErreichbar

__all__ = ["Akte", "AkteFehler", "AkteNichtErreichbar"]
__version__ = "0.3.0"
