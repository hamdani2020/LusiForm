"""CLI: create the first platform operator. Run as a one-off task (see infra/README.md).

    python -m app.bootstrap_operator --partner-name "Lusiform" \
        --email ops@example.com --cognito-sub <sub from Cognito>

The Cognito user is created first (`aws cognito-idp admin-create-user`); its `sub` links the
Cognito identity to the new Lusiform user. Refuses to run if an operator already exists.
"""

import argparse
import sys
from collections.abc import Sequence

from lusiform_common import configure_logging, get_logger

from app.config import ApiSettings
from app.data.bootstrap import BootstrapError
from app.data.database import Database


def main(argv: Sequence[str] | None = None, settings: ApiSettings | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.bootstrap_operator",
        description="Create the first Lusiform platform operator.",
    )
    parser.add_argument("--partner-name", required=True, help="Partner row for Lusiform staff")
    parser.add_argument("--email", required=True, help="The operator's email (as in Cognito)")
    parser.add_argument("--cognito-sub", required=True, help="The Cognito user's sub")
    parser.add_argument("--display-name", default=None)
    args = parser.parse_args(argv)

    settings = settings or ApiSettings()
    configure_logging("lusiform-bootstrap", settings.log_level)
    log = get_logger("bootstrap")

    db = Database.from_settings(settings)
    try:
        result = db.bootstrap_platform_operator(
            partner_name=args.partner_name,
            email=args.email,
            cognito_sub=args.cognito_sub,
            display_name=args.display_name,
        )
    except BootstrapError as exc:
        log.error("bootstrap refused", reason=str(exc))
        return 1
    finally:
        db.dispose()

    # Ids only: the email is not repeated in the logs.
    log.info(
        "platform operator created",
        partner_id=str(result.partner_id),
        user_id=str(result.user_id),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
