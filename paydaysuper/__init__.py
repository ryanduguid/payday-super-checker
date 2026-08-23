"""payday-super-checker: payday-super deadline and SG-charge exposure checker.

Educational tool. Not legal, tax or financial advice. Verify outcomes
against the ATO's own materials before acting.
"""

__version__ = "0.1.2"

LAW_CONTENT_DATE = "2026-08-15"

from .report import Result, assess

__all__ = ["LAW_CONTENT_DATE", "Result", "assess", "__version__"]
