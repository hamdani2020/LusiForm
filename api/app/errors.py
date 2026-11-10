"""Domain errors raised below the HTTP layer. `main.py` maps them to status codes."""


class NotFound(Exception):  # noqa: N818 - domain name, mapped to HTTP 404
    """The record does not exist, or belongs to another partner.

    Both cases raise this same error with the same message, so a caller cannot tell
    them apart and existence is never disclosed (Requirement 4.3). Do not add ids,
    table names or filters to the message.
    """

    def __init__(self) -> None:
        super().__init__("not found")


class NotAuthorized(Exception):  # noqa: N818 - domain name, mapped to HTTP 403
    """The caller lacks the role needed for this repository or route."""

    def __init__(self) -> None:
        super().__init__("forbidden")
