# AI-customer-support-agent\scripts\create_admin.py
from __future__ import annotations
import argparse
import getpass
import sys
from collections.abc import Sequence
from uuid6 import uuid7

from packages.application.auth.password_hasher import Argon2PasswordHasher
from packages.application.users.provision_initial_admin import InitialAdminAlreadyExistsError, InitialAdminEmailConflictError
from packages.application.users.provision_initial_admin import InitialAdminPasswordHashingError, InitialAdminPasswordPolicyError
from packages.application.users.provision_initial_admin import InitialAdminPersistenceError, ProvisionInitialAdmin, ProvisionInitialAdminCommand
from packages.config.settings import get_settings
from packages.database.session import create_session_factory
from packages.database.unit_of_work.sqlalchemy_uow import SqlAlchemyUnitOfWork

EXPECTED_DATABASE_NAME = "support_ai"

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Securely provision the initial administrator in the support_ai development database.")
    parser.add_argument("--email", required=True, help="Email address for the initial administrator.")
    parser.add_argument("--display-name", default=None, help="Optional administrator display name.")

    return parser

def _read_password() -> str:
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        raise ValueError("Password confirmation does not match.")

    return password

def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    # This intentionally loads .env, never .env.test.
    settings = get_settings("development")
    if settings.app_env != "development":
        print("Refusing to run outside the development environment.", file=sys.stderr)
        return 2

    if settings.database_name != EXPECTED_DATABASE_NAME:
        print(f"Refusing to provision an administrator: expected database {EXPECTED_DATABASE_NAME!r}, but configuration resolved {settings.database_name!r}.", file=sys.stderr)
        return 2

    print(f"Target database: {settings.database_host}:{settings.database_port}/{settings.database_name}")
    confirmation = input("Type support_ai to confirm provisioning: ").strip()
    if confirmation != EXPECTED_DATABASE_NAME:
        print("Provisioning cancelled.", file=sys.stderr)
        return 1

    try:
        password = _read_password()
        session_factory = create_session_factory(database_url=settings.database_url, echo=settings.database_echo)
        
        def uow_factory() -> SqlAlchemyUnitOfWork:
            return SqlAlchemyUnitOfWork(session_factory=session_factory)

        service = ProvisionInitialAdmin(uow_factory=uow_factory, password_hasher=Argon2PasswordHasher())
        result = service.execute(
            ProvisionInitialAdminCommand(
                email=arguments.email,
                password=password,
                display_name=arguments.display_name,
                trace_id=uuid7(),
            )
        )

    except InitialAdminAlreadyExistsError as exc:
        print(f"Provisioning refused: {exc}", file=sys.stderr)
        return 3

    except InitialAdminEmailConflictError as exc:
        print(f"Email conflict: {exc}", file=sys.stderr)
        return 4

    except InitialAdminPasswordPolicyError as exc:
        print(f"Password rejected: {exc}", file=sys.stderr)
        return 5

    except InitialAdminPasswordHashingError:
        print("Administrator password could not be securely hashed.", file=sys.stderr)
        return 6

    except InitialAdminPersistenceError:
        print("Administrator provisioning could not be persisted.", file=sys.stderr)
        return 7

    except (TypeError, ValueError) as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 8

    if result.changed:
        print("Initial administrator created successfully.")
        
    else:
        print("The requested initial administrator already exists; no database changes were made.")

    print(f"User ID: {result.user_id}")
    print(f"Email: {result.email}")
    print(f"Role: {result.role}")
    print(f"Status: {result.status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())