from .base import ReportModule
from .container_loading.module import ContainerLoadingModule

# Register new report modules here. Everything else (uploads, widget settings, nav) picks them up.
MODULES: dict[str, ReportModule] = {m.key: m for m in [ContainerLoadingModule()]}


def get_module(key: str) -> ReportModule | None:
    return MODULES.get(key)
