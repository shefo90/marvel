"""Importing this package registers every handler.

Explicit imports, not autodiscovery: a handler that fails to import must break
the worker at startup, loudly, rather than leave its jobs queued forever with
nothing to run them.
"""

from tasks import carts  # noqa: F401  (imported for its @task registrations)
