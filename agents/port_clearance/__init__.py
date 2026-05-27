"""Port Cyber Clearance E2E orchestration (Cap Vista W6)."""

__all__ = ["run_clearance"]


def __getattr__(name: str):
    if name in __all__:
        from agents.port_clearance import run_clearance as rc

        return getattr(rc, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
