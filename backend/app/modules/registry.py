from .base import ReportModule
from .bom_verification.module import BomVerificationModule
from .container_loading.module import ContainerLoadingModule
from .pre_production_audit.module import PreProductionAuditModule
from .pre_shipment.module import PreShipmentModule
from .production_supervision.module import ProductionSupervisionModule

# Register new report modules here. Everything else (uploads, widget settings, nav) picks them up.
MODULES: dict[str, ReportModule] = {m.key: m for m in [ContainerLoadingModule(), ProductionSupervisionModule(), PreShipmentModule(),
                                                       BomVerificationModule(), PreProductionAuditModule()]}


def get_module(key: str) -> ReportModule | None:
    return MODULES.get(key)
