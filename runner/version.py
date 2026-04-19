"""SDK version pin for forge-runner.

FR-039: the pinned version constant must match the installed
claude-agent-sdk.__version__ at runtime.  The drift test
(tests/forge_runner/test_version_drift.py) asserts this at CI time.
check_sdk_version() does the runtime check — it logs a WARN on drift but
does NOT raise, so a minor SDK patch bump does not abort the runner.
"""

from __future__ import annotations

import importlib.metadata

import structlog

logger = structlog.get_logger(__name__)

PINNED_SDK_VERSION: str = "0.1.58"


def check_sdk_version() -> None:
    """Compare the installed claude-agent-sdk version against the pinned pin.

    Logs a structlog WARN if there is a drift.  Does NOT raise — the runner
    continues with a warning so that a minor patch bump does not cause an
    outage.  Operators should pin the version intentionally and update
    PINNED_SDK_VERSION when they upgrade.
    """
    installed: str | None = None

    # Prefer __version__ attribute (set by most modern packages).
    try:
        import claude_agent_sdk  # type: ignore[import-untyped,unused-ignore]

        installed = getattr(claude_agent_sdk, "__version__", None)
    except ImportError:
        logger.warning(
            "sdk_import_failed",
            msg="claude_agent_sdk not importable; cannot check version drift",
        )
        return

    # Fall back to importlib.metadata if __version__ is absent.
    if installed is None:
        try:
            installed = importlib.metadata.version("claude-agent-sdk")
        except importlib.metadata.PackageNotFoundError:
            logger.warning(
                "sdk_version_unknown",
                msg="claude-agent-sdk not found via importlib.metadata",
            )
            return

    if installed != PINNED_SDK_VERSION:
        logger.warning(
            "sdk_version_drift",
            pinned=PINNED_SDK_VERSION,
            installed=installed,
            msg=(
                f"Installed claude-agent-sdk {installed!r} differs from "
                f"pinned {PINNED_SDK_VERSION!r}. Update PINNED_SDK_VERSION "
                "in scripts/forge_runner/version.py when intentionally upgrading."
            ),
        )
    else:
        logger.debug(
            "sdk_version_ok",
            version=installed,
        )
