# AI-customer-support-agent\apps\api\app\api\errors.py
from __future__ import annotations
import logging
import uuid
from uuid6 import uuid7
from collections.abc import Mapping
from typing import Any
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.api.app.api.dependencies import TRACE_HEADER_NAME
from packages.application.conversations.process_customer_message import ConversationDoesNotExistError, ConversationNotProcessableError, CustomerMessageValidationError
from packages.application.escalations.create_escalation import CreateEscalationContractError, CreateEscalationError, EscalationIdempotencyConflictError
from packages.application.escalations.query_escalations import EscalationDoesNotExistError as QueriedEscalationDoesNotExistError
from packages.application.escalations.query_escalations import EscalationQueryContractError, EscalationQueryError
from packages.application.escalations.update_escalation import EscalationDoesNotExistError as UpdatedEscalationDoesNotExistError
from packages.application.escalations.update_escalation import EscalationPersistenceContractError, InvalidEscalationTransitionError, UpdateEscalationError
from packages.application.tickets.add_ticket_comment import AddTicketCommentError, CommentAuthorDoesNotExistError, CommentAuthorNotActiveError
from packages.application.tickets.add_ticket_comment import CommentAuthorRoleMismatchError, CommentTicketDoesNotExistError, CustomerInternalCommentError
from packages.application.tickets.add_ticket_comment import TicketCommentOwnershipError, TicketCommentPersistenceContractError, TicketNotCommentableError
from packages.application.tickets.create_ticket import CreateTicketError, TicketConversationDoesNotExistError, TicketConversationOwnershipError
from packages.application.tickets.create_ticket import TicketCustomerDoesNotExistError, TicketCustomerNotActiveError, TicketEscalationDoesNotExistError
from packages.application.tickets.create_ticket import TicketEscalationMismatchError, TicketEscalationNotActiveError, TicketIdempotencyConflictError
from packages.application.tickets.create_ticket import TicketPersistenceContractError as CreateTicketPersistenceContractError
from packages.application.tickets.create_ticket import TicketSourceMessageDoesNotExistError, TicketSourceMessageMismatchError
from packages.application.tickets.query_tickets import TicketAccessDeniedError, TicketDoesNotExistError as QueriedTicketDoesNotExistError
from packages.application.tickets.query_tickets import TicketQueryContractError, TicketQueryError, TicketRequesterDoesNotExistError
from packages.application.tickets.query_tickets import TicketRequesterNotActiveError, TicketRequesterRoleMismatchError
from packages.application.tickets.update_ticket import ClosedTicketMutationError, InvalidTicketTransitionError, TicketAgentDoesNotExistError
from packages.application.tickets.update_ticket import TicketAgentNotAssignableError, TicketConcurrencyError, UpdateTicketError, TicketUpdateAccessDeniedError
from packages.application.tickets.update_ticket import TicketDoesNotExistError as UpdatedTicketDoesNotExistError
from packages.application.tickets.update_ticket import TicketPersistenceContractError as UpdateTicketPersistenceContractError
from packages.application.feedback.query_feedback import FeedbackAccessDeniedError, FeedbackDoesNotExistError, FeedbackQueryContractError
from packages.application.feedback.query_feedback import FeedbackQueryError, FeedbackRequesterDoesNotExistError
from packages.application.feedback.query_feedback import FeedbackRequesterNotActiveError, FeedbackRequesterRoleMismatchError
from packages.application.feedback.review_feedback import FeedbackReviewerDoesNotExistError, FeedbackReviewerNotAuthorizedError
from packages.application.feedback.review_feedback import FeedbackReviewConcurrencyError, FeedbackReviewPersistenceContractError
from packages.application.feedback.review_feedback import InvalidFeedbackTransitionError, ReviewFeedbackDoesNotExistError, ReviewFeedbackError
from packages.application.feedback.submit_feedback import FeedbackAIRunDoesNotExistError, FeedbackAIRunMismatchError, FeedbackConversationDoesNotExistError
from packages.application.feedback.submit_feedback import FeedbackConversationOwnershipError, FeedbackCustomerDoesNotExistError
from packages.application.feedback.submit_feedback import FeedbackCustomerNotActiveError, FeedbackCustomerRoleError, SubmitFeedbackError
from packages.application.feedback.submit_feedback import FeedbackPersistenceContractError, FeedbackResponseMessageDoesNotExistError
from packages.application.feedback.submit_feedback import FeedbackResponseMessageMismatchError, FeedbackSubmissionConflictError
from packages.application.auth.exceptions import *
from packages.application.escalations.get_customer_escalation_status import CustomerConversationNotAccessibleError, CustomerEscalationDoesNotExistError, CustomerEscalationStatusContractError
from packages.application.tickets.create_ticket import TicketCreationAccessDeniedError
from packages.application.feedback.submit_feedback import FeedbackSubmissionAccessDeniedError

logger = logging.getLogger(__name__)

# Public error codes
ERROR_INVALID_REQUEST = "INVALID_REQUEST"
ERROR_INVALID_TRACE_ID = "INVALID_TRACE_ID"
ERROR_CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
ERROR_CONVERSATION_NOT_PROCESSABLE = "CONVERSATION_NOT_PROCESSABLE"
ERROR_INVALID_CUSTOMER_MESSAGE = "INVALID_CUSTOMER_MESSAGE"
ERROR_INTERNAL = "INTERNAL_ERROR"
ERROR_ESCALATION_NOT_FOUND = "ESCALATION_NOT_FOUND"
ERROR_INVALID_ESCALATION_OPERATION = "INVALID_ESCALATION_OPERATION"
ERROR_ESCALATION_CONFLICT = "ESCALATION_CONFLICT"
ERROR_CUSTOMER_ESCALATION_STATUS_NOT_FOUND = "CUSTOMER_ESCALATION_STATUS_NOT_FOUND"
ERROR_TICKET_NOT_FOUND = "TICKET_NOT_FOUND"
ERROR_TICKET_RELATED_RESOURCE_NOT_FOUND = "TICKET_RELATED_RESOURCE_NOT_FOUND"
ERROR_TICKET_ACCESS_DENIED = "TICKET_ACCESS_DENIED"
ERROR_INVALID_TICKET_OPERATION = "INVALID_TICKET_OPERATION"
ERROR_TICKET_CONFLICT = "TICKET_CONFLICT"
ERROR_TICKET_CONCURRENT_UPDATE = "TICKET_CONCURRENT_UPDATE"
ERROR_FEEDBACK_NOT_FOUND = "FEEDBACK_NOT_FOUND"
ERROR_FEEDBACK_RELATED_RESOURCE_NOT_FOUND = "FEEDBACK_RELATED_RESOURCE_NOT_FOUND"
ERROR_FEEDBACK_ACCESS_DENIED = "FEEDBACK_ACCESS_DENIED"
ERROR_INVALID_FEEDBACK_OPERATION = "INVALID_FEEDBACK_OPERATION"
ERROR_FEEDBACK_CONFLICT = "FEEDBACK_CONFLICT"
ERROR_FEEDBACK_CONCURRENT_UPDATE = "FEEDBACK_CONCURRENT_UPDATE"
ERROR_EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
ERROR_PASSWORD_POLICY_VIOLATION = "PASSWORD_POLICY_VIOLATION"
ERROR_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
ERROR_INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
ERROR_UNAUTHENTICATED = "UNAUTHENTICATED"

# Registration
def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all API-level exception handlers.

    This is the single boundary where internal/application exceptions are translated into stable HTTP responses.

    Route handlers should generally allow known application exceptions to propagate here rather than duplicating try/except blocks.
    """

    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(ConversationDoesNotExistError, conversation_not_found_handler)
    app.add_exception_handler(ConversationNotProcessableError, conversation_not_processable_handler)
    app.add_exception_handler(CustomerMessageValidationError, customer_message_validation_handler)
    
    for exception_type in (QueriedEscalationDoesNotExistError, UpdatedEscalationDoesNotExistError):
        app.add_exception_handler(exception_type, escalation_not_found_handler)

    for exception_type in (InvalidEscalationTransitionError, EscalationIdempotencyConflictError):
        app.add_exception_handler(exception_type, escalation_conflict_handler)

    for exception_type in (CreateEscalationError, EscalationQueryError, UpdateEscalationError):
        app.add_exception_handler(exception_type, invalid_escalation_operation_handler)

    for exception_type in (CreateEscalationContractError, EscalationQueryContractError, EscalationPersistenceContractError):
        app.add_exception_handler(exception_type, escalation_internal_contract_handler)
        
    for exception_type in (CustomerConversationNotAccessibleError, CustomerEscalationDoesNotExistError):
        app.add_exception_handler(exception_type, customer_escalation_status_not_found_handler)

    app.add_exception_handler(CustomerEscalationStatusContractError, escalation_internal_contract_handler)
    
    for exception_type in (QueriedTicketDoesNotExistError, UpdatedTicketDoesNotExistError, CommentTicketDoesNotExistError):
        app.add_exception_handler(exception_type, ticket_not_found_handler)

    for exception_type in (
        TicketConversationDoesNotExistError, TicketCustomerDoesNotExistError, TicketSourceMessageDoesNotExistError,
        TicketEscalationDoesNotExistError, CommentAuthorDoesNotExistError, TicketAgentDoesNotExistError, TicketRequesterDoesNotExistError
    ):
        app.add_exception_handler(exception_type, ticket_related_resource_not_found_handler)

    for exception_type in (
        TicketConversationOwnershipError, TicketCustomerNotActiveError, TicketCommentOwnershipError, CustomerInternalCommentError, TicketUpdateAccessDeniedError,
        CommentAuthorNotActiveError, CommentAuthorRoleMismatchError, TicketAccessDeniedError, TicketRequesterNotActiveError, TicketRequesterRoleMismatchError, TicketCreationAccessDeniedError,
    ):
        app.add_exception_handler(exception_type, ticket_access_denied_handler)

    app.add_exception_handler(TicketConcurrencyError,ticket_concurrency_handler)

    for exception_type in (
        InvalidTicketTransitionError, ClosedTicketMutationError, TicketNotCommentableError, TicketAgentNotAssignableError,
        TicketEscalationNotActiveError, TicketIdempotencyConflictError
    ):
        app.add_exception_handler(exception_type, ticket_conflict_handler)

    for exception_type in (
        TicketSourceMessageMismatchError, TicketEscalationMismatchError, CreateTicketError, AddTicketCommentError, UpdateTicketError, TicketQueryError
    ):
        app.add_exception_handler(exception_type, invalid_ticket_operation_handler)

    for exception_type in (CreateTicketPersistenceContractError, TicketCommentPersistenceContractError, UpdateTicketPersistenceContractError, TicketQueryContractError):
        app.add_exception_handler(exception_type, ticket_internal_contract_handler)
        
    for exception_type in (FeedbackDoesNotExistError, ReviewFeedbackDoesNotExistError):
        app.add_exception_handler(exception_type, feedback_not_found_handler)

    for exception_type in (
        FeedbackConversationDoesNotExistError, FeedbackCustomerDoesNotExistError, FeedbackResponseMessageDoesNotExistError,
        FeedbackAIRunDoesNotExistError, FeedbackRequesterDoesNotExistError, FeedbackReviewerDoesNotExistError
    ):
        app.add_exception_handler(exception_type, feedback_related_resource_not_found_handler)

    for exception_type in (
        FeedbackConversationOwnershipError, FeedbackCustomerNotActiveError, FeedbackCustomerRoleError, FeedbackAccessDeniedError,
        FeedbackRequesterNotActiveError, FeedbackRequesterRoleMismatchError, FeedbackReviewerNotAuthorizedError, FeedbackSubmissionAccessDeniedError,
    ):
        app.add_exception_handler(exception_type, feedback_access_denied_handler)

    app.add_exception_handler(FeedbackReviewConcurrencyError, feedback_concurrency_handler)

    for exception_type in (FeedbackSubmissionConflictError, InvalidFeedbackTransitionError):
        app.add_exception_handler(exception_type, feedback_conflict_handler)

    for exception_type in (
        FeedbackResponseMessageMismatchError, FeedbackAIRunMismatchError, SubmitFeedbackError, FeedbackQueryError, ReviewFeedbackError
    ):
        app.add_exception_handler(exception_type, invalid_feedback_operation_handler)

    for exception_type in (FeedbackPersistenceContractError, FeedbackQueryContractError, FeedbackReviewPersistenceContractError):
        app.add_exception_handler(exception_type, feedback_internal_contract_handler)
        
    # Authentication errors
    app.add_exception_handler(RegistrationConflictError, registration_conflict_handler)
    app.add_exception_handler(RegistrationPasswordPolicyError, registration_password_policy_handler)
    app.add_exception_handler(InvalidCredentialsError, invalid_credentials_handler)
    app.add_exception_handler(InvalidRefreshTokenError, invalid_refresh_token_handler)

    for exception_type in (CurrentUserUnavailableError, CurrentUserStateConflictError):
        app.add_exception_handler(exception_type, current_user_unavailable_handler)

    for exception_type in (
        RegistrationConfigurationError, RegistrationPasswordHashingError, RegistrationPersistenceError, LoginConfigurationError,
        LoginPasswordHashingError,LoginPersistenceError, RefreshSessionConfigurationError, RefreshSessionPersistenceError,
        LogoutConfigurationError, LogoutPersistenceError, LogoutSessionOwnershipError, GetCurrentUserPersistenceError,
        AccessAuthenticationConfigurationError, AccessAuthenticationPersistenceError,
    ):
        app.add_exception_handler(exception_type, authentication_internal_error_handler)

    # Must remain last conceptually: this is the safety net for unexpected failures.
    app.add_exception_handler(Exception, unhandled_exception_handler)


# Application exception handlers
async def conversation_not_found_handler(request: Request, exc: ConversationDoesNotExistError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "conversation_not_found",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_CONVERSATION_NOT_FOUND,
        message="The requested conversation does not exist.",
        trace_id=trace_id,
    )

async def conversation_not_processable_handler(request: Request, exc: ConversationNotProcessableError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "conversation_not_processable",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_CONVERSATION_NOT_PROCESSABLE,
        message="The conversation cannot accept a new customer message in its current state.",
        trace_id=trace_id,
    )

async def customer_message_validation_handler(request: Request, exc: CustomerMessageValidationError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "customer_message_validation_failed",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
        },
    )
    # Do not automatically expose str(exc) to external callers.
    # Application exceptions can later contain internal details.
    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ERROR_INVALID_CUSTOMER_MESSAGE,
        message="The customer message is invalid.",
        trace_id=trace_id,
    )
    
async def escalation_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "escalation_not_found",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_ESCALATION_NOT_FOUND,
        message="The requested escalation does not exist.",
        trace_id=trace_id,
    )

async def escalation_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "escalation_operation_conflict",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_ESCALATION_CONFLICT,
        message="The escalation operation conflicts with the escalation's current state.",
        trace_id=trace_id,
    )

async def invalid_escalation_operation_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "invalid_escalation_operation",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ERROR_INVALID_ESCALATION_OPERATION,
        message="The requested escalation operation is invalid.",
        trace_id=trace_id,
    )

async def escalation_internal_contract_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.exception(
        "escalation_internal_contract_failure",
        exc_info=exc,
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ERROR_INTERNAL,
        message="An unexpected internal error occurred.",
        trace_id=trace_id,
    )
    
async def customer_escalation_status_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "customer_escalation_status_unavailable",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_CUSTOMER_ESCALATION_STATUS_NOT_FOUND,
        message="Escalation status is unavailable for the requested conversation.",
        trace_id=trace_id,
    )
    
async def ticket_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "ticket_not_found",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_TICKET_NOT_FOUND,
        message="The requested ticket does not exist.",
        trace_id=trace_id,
    )

async def ticket_related_resource_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "ticket_related_resource_not_found",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_TICKET_RELATED_RESOURCE_NOT_FOUND,
        message="A conversation, user, message, escalation, or agent required by the ticket operation does not exist.",
        trace_id=trace_id,
    )

async def ticket_access_denied_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.warning(
        "ticket_access_denied",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        code=ERROR_TICKET_ACCESS_DENIED,
        message="You are not permitted to perform this ticket operation.",
        trace_id=trace_id,
    )

async def invalid_ticket_operation_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "invalid_ticket_operation",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ERROR_INVALID_TICKET_OPERATION,
        message="The requested ticket operation is invalid.",
        trace_id=trace_id,
    )

async def ticket_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "ticket_operation_conflict",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_TICKET_CONFLICT,
        message="The ticket operation conflicts with the ticket's current state.",
        trace_id=trace_id,
    )

async def ticket_concurrency_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "ticket_concurrent_update",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_TICKET_CONCURRENT_UPDATE,
        message="The ticket was modified by another operation. Refresh the ticket and retry using its latest row version.",
        trace_id=trace_id,
    )

async def ticket_internal_contract_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.exception(
        "ticket_internal_contract_failure",
        exc_info=exc,
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ERROR_INTERNAL,
        message="An unexpected internal error occurred.",
        trace_id=trace_id,
    )
    
async def feedback_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "feedback_not_found",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_FEEDBACK_NOT_FOUND,
        message="The requested feedback does not exist.",
        trace_id=trace_id,
    )

async def feedback_related_resource_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "feedback_related_resource_not_found",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=ERROR_FEEDBACK_RELATED_RESOURCE_NOT_FOUND,
        message="A conversation, customer, response message, AI run, requester, or reviewer required by the feedback operation does not exist.",
        trace_id=trace_id,
    )

async def feedback_access_denied_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.warning(
        "feedback_access_denied",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_403_FORBIDDEN,
        code=ERROR_FEEDBACK_ACCESS_DENIED,
        message="You are not permitted to perform this feedback operation.",
        trace_id=trace_id,
    )

async def invalid_feedback_operation_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "invalid_feedback_operation",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ERROR_INVALID_FEEDBACK_OPERATION,
        message="The requested feedback operation is invalid.",
        trace_id=trace_id,
    )

async def feedback_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "feedback_operation_conflict",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_FEEDBACK_CONFLICT,
        message="The feedback operation conflicts with existing feedback or its current review state.",
        trace_id=trace_id,
    )


async def feedback_concurrency_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "feedback_concurrent_update",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_FEEDBACK_CONCURRENT_UPDATE,
        message="The feedback was modified by another operation. Refresh it and retry using the latest row version.",
        trace_id=trace_id,
    )

async def feedback_internal_contract_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.exception(
        "feedback_internal_contract_failure",
        exc_info=exc,
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ERROR_INTERNAL,
        message="An unexpected internal error occurred.",
        trace_id=trace_id,
    )
    
# Authentication exception handlers
async def registration_conflict_handler(request: Request, exc: RegistrationConflictError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "registration_conflict",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_409_CONFLICT,
        code=ERROR_EMAIL_ALREADY_REGISTERED,
        message="An account already exists for this email address.",
        trace_id=trace_id,
    )

async def registration_password_policy_handler(request: Request, exc: RegistrationPasswordPolicyError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "registration_password_policy_rejected",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ERROR_PASSWORD_POLICY_VIOLATION,
        message="The supplied password does not satisfy the password policy.",
        trace_id=trace_id,
    )

async def invalid_credentials_handler(request: Request, exc: InvalidCredentialsError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "login_rejected",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=ERROR_INVALID_CREDENTIALS,
        message="The email or password is invalid.",
        trace_id=trace_id,
        headers={"WWW-Authenticate": "Bearer",},
    )

async def invalid_refresh_token_handler(request: Request, exc: InvalidRefreshTokenError) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "refresh_token_rejected",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=ERROR_INVALID_REFRESH_TOKEN,
        message="The refresh token is invalid or expired.",
        trace_id=trace_id,
        headers={"WWW-Authenticate": "Bearer",},
    )

async def current_user_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.info(
        "current_user_unavailable",
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=ERROR_UNAUTHENTICATED,
        message="Valid authentication credentials are required.",
        trace_id=trace_id,
        headers={"WWW-Authenticate": "Bearer",},
    )


async def authentication_internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = _resolve_trace_id(request)
    logger.exception(
        "authentication_internal_failure",
        exc_info=exc,
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ERROR_INTERNAL,
        message="An unexpected internal error occurred.",
        trace_id=trace_id,
    )

# FastAPI / HTTP exception handlers
async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Convert FastAPI/Pydantic validation failures into our stable API error format.
    """
    trace_id = _resolve_trace_id(request)
    validation_issues = [
        {
            "location": [str(part) for part in error.get("loc", ())],
            "message": str(error.get("msg", "Invalid value.")),
            "type": str(error.get("type", "validation_error",))
        }
        for error in exc.errors()
    ]

    logger.info(
        "request_validation_failed",
        extra={
            "trace_id": str(trace_id),
            "path": request.url.path,
            "method": request.method,
            "validation_error_count": len(validation_issues)
        },
    )

    return _error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code=ERROR_INVALID_REQUEST,
        message="The request contains invalid data.",
        trace_id=trace_id,
        details=validation_issues,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Normalize FastAPI HTTPException instances into the same error envelope.

    This is particularly useful for dependencies such as trace-ID
    validation.
    """
    trace_id = _resolve_trace_id(request)
    code = ERROR_INVALID_REQUEST
    message = "The request could not be processed."
    detail = exc.detail

    if isinstance(detail, Mapping):
        detail_code = detail.get("code")
        detail_message = detail.get("message")
        if isinstance(detail_code, str) and detail_code:
            code = detail_code

        if isinstance(detail_message, str) and detail_message:
            message = detail_message

    elif isinstance(detail, str) and detail:
        message = detail

    return _error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        trace_id=trace_id,
        headers=exc.headers,
    )

# Unexpected failures
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last-resort API safety boundary.

    Full exception information is logged internally, while callers receive
    a stable non-sensitive response.
    """
    trace_id = _resolve_trace_id(request)
    logger.exception(
        "unhandled_api_exception",
        exc_info=exc,
        extra={
            "trace_id": str(trace_id),
            "method": request.method,
            "path": request.url.path,
        },
    )

    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=ERROR_INTERNAL,
        message="An unexpected internal error occurred.",
        trace_id=trace_id,
    )

# Response construction
def _error_response(*, status_code: int, code: str, message: str, trace_id: uuid.UUID,
                    details: list[dict[str, Any]] | None = None, headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """
    Construct the canonical API error response.

    Every error:
    - follows the same JSON structure
    - contains a trace ID
    - exposes the trace ID as an HTTP response header
    """
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "trace_id": str(trace_id),
        }
    }
    if details:
        body["error"]["details"] = details

    response_headers = dict(headers or {})
    response_headers[TRACE_HEADER_NAME] = str(trace_id)
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers=response_headers,
    )

# Trace resolution
def _resolve_trace_id(request: Request) -> uuid.UUID:
    """
    Return the request trace ID when available.

    Exception handlers can run before normal endpoint dependencies have
    executed, for example when path/body validation fails. Therefore they
    cannot assume request.state.trace_id already exists.
    """

    existing = getattr(request.state, "trace_id", None)
    if isinstance(existing, uuid.UUID):
        return existing

    trace_id = uuid7()
    request.state.trace_id = trace_id
    return trace_id