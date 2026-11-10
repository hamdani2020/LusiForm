"""The only place a database session is created.

Handlers never receive a raw session. They open a unit of work with a
`RequestContext` and get repositories bound to it; the transaction commits on
success and rolls back on error. The engine and session factory are private.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import ApiSettings
from app.context import RequestContext
from app.data.identity import Identity, resolve_identity
from app.data.repositories import (
    AuditEventRepository,
    IntakeDraftRepository,
    PartnerRepository,
    ProjectRepository,
    TemplateVersionRepository,
    UserRepository,
    UserRoleRepository,
)


class TenantRepositories:
    """Repositories scoped to the caller's partner. Holds the session privately."""

    def __init__(self, ctx: RequestContext, session: Session) -> None:
        self.users = UserRepository(ctx, session)
        self.user_roles = UserRoleRepository(ctx, session)
        self.projects = ProjectRepository(ctx, session)
        self.intake_drafts = IntakeDraftRepository(ctx, session)
        self.audit_events = AuditEventRepository(ctx, session)


class OperatorRepositories:
    """Cross-partner repositories. Construction fails unless the caller is a platform operator."""

    def __init__(self, ctx: RequestContext, session: Session) -> None:
        self.partners = PartnerRepository(ctx, session)
        self.template_versions = TemplateVersionRepository(ctx, session)


class Database:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_settings(cls, settings: ApiSettings) -> "Database":
        if settings.database_url is None:
            raise RuntimeError("DATABASE_URL is not set")
        return cls(create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True))

    @contextmanager
    def tenant(self, ctx: RequestContext) -> Iterator[TenantRepositories]:
        with self._sessions() as session, session.begin():
            yield TenantRepositories(ctx, session)

    @contextmanager
    def operator(self, ctx: RequestContext) -> Iterator[OperatorRepositories]:
        with self._sessions() as session, session.begin():
            yield OperatorRepositories(ctx, session)

    def resolve_identity(self, cognito_sub: str) -> Identity | None:
        """Look up the caller by verified Cognito subject (pre-context; see identity.py)."""
        with self._sessions() as session:
            return resolve_identity(session, cognito_sub)

    def dispose(self) -> None:
        self._engine.dispose()
