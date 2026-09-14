# AI-customer-support-agent\packages\application\auth\exceptions.py
from enum import StrEnum

# Password Hash
class PasswordHashingError(RuntimeError):
    """Raised when a password cannot be securely hashed."""
    
# Registration
class RegistrationError(RuntimeError):
    """Base exception for user-registration failures."""

class RegistrationConflictError(RegistrationError):
    """Raised when the email address is already registered."""

class RegistrationPasswordPolicyError(RegistrationError):
    """Raised when a password does not satisfy registration policy."""

class RegistrationPersistenceError(RegistrationError):
    """Raised when required persistence components are unavailable."""

class RegistrationConfigurationError(RegistrationError):
    """Raised when authentication configuration is invalid."""

class RegistrationPasswordHashingError(RegistrationError):
    """Raised when password hashing fails unexpectedly."""

# Token
class AccessTokenError(ValueError):
    """Base exception for invalid access tokens."""

class AccessTokenExpiredError(AccessTokenError):
    """Raised when an otherwise valid access token has expired."""

class InvalidAccessTokenError(AccessTokenError):
    """Raised when an access token is malformed or untrusted."""

# Refresh Session
class RefreshSessionError(RuntimeError):
    """Base exception for refresh-session failures."""

class InvalidRefreshTokenError(RefreshSessionError):
    """
    Public refresh failure.

    Unknown, expired, revoked, reused, and account-invalid refresh tokens deliberately produce the same public error.
    """
    def __init__(self) -> None:
        super().__init__("The refresh token is invalid or expired.")

class RefreshSessionPersistenceError(RefreshSessionError):
    """Raised when refresh rotation cannot be persisted."""

class RefreshSessionConfigurationError(RefreshSessionError):
    """Raised when authentication configuration is inconsistent."""
    
# Login
class LoginError(RuntimeError):
    """Base exception for login failures."""

class InvalidCredentialsError(LoginError):
    """
    Public authentication failure.

    Unknown email addresses, incorrect passwords, disabled accounts, and locked accounts intentionally use the same public exception.
    """
    def __init__(self) -> None:
        super().__init__("Invalid email or password.")

class LoginPersistenceError(LoginError):
    """Raised when login persistence cannot be completed."""

class LoginConfigurationError(LoginError):
    """Raised when authentication configuration is invalid."""

class LoginPasswordHashingError(LoginError):
    """Raised when password rehashing fails unexpectedly."""

# Logout
class LogoutError(RuntimeError):
    """Base exception for logout failures."""

class LogoutSessionOwnershipError(LogoutError):
    """
    Raised when a trusted principal references a session belonging to a different user.

    This indicates corrupted state or an incorrectly constructed principal.
    """

class LogoutPersistenceError(LogoutError):
    """Raised when logout persistence components are unavailable."""

class LogoutConfigurationError(LogoutError):
    """Raised when authentication configuration is inconsistent."""
    
# Authentication
class AccessAuthenticationError(RuntimeError):
    """Base exception for access-token authentication failures."""
    
class AccessAuthenticationReason(StrEnum):
    TOKEN_INVALID = "token_invalid"
    TOKEN_EXPIRED = "token_expired"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_USER_MISMATCH = "session_user_mismatch"
    SESSION_REVOKED = "session_revoked"
    SESSION_EXPIRED = "session_expired"
    USER_NOT_FOUND = "user_not_found"
    USER_INACTIVE = "user_inactive"
    ROLE_CHANGED = "role_changed"
    ROLE_NOT_INTERACTIVE = "role_not_interactive"

class AccessAuthenticationRejectedError(AccessAuthenticationError):
    """
    Safe public authentication rejection.

    The API should return the same 401 response for every reason. The reason code is suitable for internal
    structured logs but must not be used to disclose account or session state to the caller.
    """
    def __init__(self, reason: AccessAuthenticationReason) -> None:
        self.reason = reason
        super().__init__("Authentication credentials are invalid or expired.")
        
class AccessAuthenticationPersistenceError(AccessAuthenticationError):
    """Raised when authentication persistence is unavailable."""

class AccessAuthenticationConfigurationError(AccessAuthenticationError):
    """Raised when trusted authentication state is inconsistent."""

# User
class GetCurrentUserError(RuntimeError):
    """Base exception for current-user queries."""

class CurrentUserUnavailableError(GetCurrentUserError):
    """
    Raised when the authenticated user or their local credential no longer exists or is unavailable.
    """

class CurrentUserStateConflictError(GetCurrentUserError):
    """
    Raised when the trusted principal no longer matches current database identity state.
    """

class GetCurrentUserPersistenceError(GetCurrentUserError):
    """Raised when required repositories are unavailable."""
    
