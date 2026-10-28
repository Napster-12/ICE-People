"""Integration plumbing: every adapter call is logged, and failures are retried.

Each external system has an interface (abstract class) and a Mock* implementation.
The implementation used is chosen by the INTEGRATIONS config mapping, so a real
adapter can be plugged in later without touching business code.
"""
import importlib
import logging

from flask import current_app

from app.extensions import db

log = logging.getLogger("integrations")


class IntegrationError(Exception):
    pass


class Adapter:
    system = "base"

    def __init__(self):
        # Tests can force failures: {"method_name": number_of_failures_before_success}
        self.forced_failures = {}

    def call(self, method, payload, fn):
        """Run `fn()` with logging and retry. Returns its result or raises IntegrationError."""
        from app.models import IntegrationLog

        retries = current_app.config.get("INTEGRATION_RETRIES", 2)
        last_error = None
        for attempt in range(1, retries + 2):
            try:
                if self.forced_failures.get(method, 0) > 0:
                    self.forced_failures[method] -= 1
                    raise IntegrationError(f"Simulated {self.system} failure")
                result = fn()
                db.session.add(IntegrationLog(system=self.system, method=method, request=_jsonable(payload),
                                              response=_jsonable(result), success=True, attempt=attempt))
                return result
            except Exception as exc:  # noqa: BLE001 - every failure is logged and retried
                last_error = exc
                log.warning("%s.%s attempt %s failed: %s", self.system, method, attempt, exc)
                db.session.add(IntegrationLog(system=self.system, method=method, request=_jsonable(payload),
                                              success=False, attempt=attempt, error=str(exc)[:500]))
        raise IntegrationError(f"{self.system}.{method} failed after {retries + 1} attempts: {last_error}")


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


_instances = {}


def get_adapter(system):
    """The configured adapter instance for `system` (e.g. "payroll")."""
    path = current_app.config["INTEGRATIONS"][system]
    if path not in _instances:
        module_name, class_name = path.split(":")
        cls = getattr(importlib.import_module(module_name), class_name)
        _instances[path] = cls()
    return _instances[path]
