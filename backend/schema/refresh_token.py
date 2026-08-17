"""Refresh rotation contract.

Zero logic. Pydantic models only.

Rotation returns a *new pair*, not a new access token alone — the old refresh
token is revoked as part of the exchange, so a client that only replaced its
access token would be left holding a dead refresh token. Reusing ``token_pair``
makes that structurally obvious rather than a line of documentation.

There is no request body: the refresh token travels in the ``Authorization``
header like any other bearer credential, which keeps it out of request logs that
capture bodies and out of any client code tempted to put it in a query string.
"""

from schema.login import token_pair


class refresh_response(token_pair):
    pass
