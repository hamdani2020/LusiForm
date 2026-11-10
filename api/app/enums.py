"""Value sets shared by the data layer and the API. No ORM imports here."""

from enum import StrEnum


class Role(StrEnum):
    PARTNER_ADMIN = "partner_admin"
    CONSULTANT = "consultant"
    PLATFORM_OPERATOR = "platform_operator"


class PartnerStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SandboxStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    DISABLED = "disabled"


class CheckStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class DeploymentAction(StrEnum):
    APPLY = "apply"
    DESTROY = "destroy"


class PlanStatus(StrEnum):
    READY = "ready"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
