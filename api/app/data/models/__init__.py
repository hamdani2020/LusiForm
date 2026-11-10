"""All ORM models. Import this package to register every table on `Base.metadata`."""

from app.data.models.base import Base
from app.data.models.sandbox import (
    ArchitectureGraph,
    AuditEvent,
    Deployment,
    DeploymentPlan,
    DiagramArtifact,
    PlanApproval,
    SandboxAccount,
)
from app.data.models.tenant import IntakeDraft, Partner, Project, User, UserRole
from app.data.models.versions import (
    Artifact,
    AssumptionSet,
    Estimate,
    GenerationJob,
    ProjectVersion,
    TemplateVersion,
    ValidationRun,
)

__all__ = [
    "ArchitectureGraph",
    "Artifact",
    "AssumptionSet",
    "AuditEvent",
    "Base",
    "Deployment",
    "DeploymentPlan",
    "DiagramArtifact",
    "Estimate",
    "GenerationJob",
    "IntakeDraft",
    "Partner",
    "PlanApproval",
    "Project",
    "ProjectVersion",
    "SandboxAccount",
    "TemplateVersion",
    "User",
    "UserRole",
    "ValidationRun",
]
