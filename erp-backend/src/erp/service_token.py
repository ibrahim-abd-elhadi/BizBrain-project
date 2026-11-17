"""Issue the Brain's service token for the Canonical API (feature 002, research R-03).

    docker compose exec -T erp-backend python -m erp.service_token issue > secrets/brain_service_token

Only the token goes to stdout, so the redirect stores it and nothing else. The jti and the expiry
go to stderr; the token never does. `secrets/` is git-ignored. The ERP keeps no list of tokens: to
replace one, issue a new token and restart the Brain.
"""

import argparse
import sys

from erp.security import SERVICE_SCOPES, create_service_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m erp.service_token", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    issue = commands.add_parser("issue", help="sign a new service token and print it")
    issue.add_argument(
        "--days", type=int, help="lifetime in days (default: ERP_SERVICE_TOKEN_TTL_DAYS)"
    )
    issue.add_argument(
        "--scope",
        action="append",
        choices=SERVICE_SCOPES,
        help="grant only this scope (repeatable; default: all Canonical scopes)",
    )
    args = parser.parse_args(argv)
    if args.days is not None and args.days <= 0:
        parser.error("--days must be greater than 0")

    token, jti, expires_at = create_service_token(
        scopes=tuple(args.scope) if args.scope else SERVICE_SCOPES, days=args.days
    )
    print(token)
    expiry = expires_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"issued Brain service token jti={jti} expires={expiry}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
