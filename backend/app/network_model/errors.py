"""Domain errors. The API layer maps each to an HTTP status code."""


class NetworkModelError(Exception):
    status_code = 400


class InvalidNetworkData(NetworkModelError):
    """The request is well-formed but breaks a networking rule (HTTP 422)."""

    status_code = 422


class NotFoundError(NetworkModelError):
    status_code = 404


class ConflictError(NetworkModelError):
    """The change clashes with existing data (HTTP 409)."""

    status_code = 409
