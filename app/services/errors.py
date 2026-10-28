class DomainError(Exception):
    """A business rule was broken. The message is safe to show to the user."""


class StateMachine:
    """Explicit allowed transitions for a workflow entity's status."""

    def __init__(self, name, transitions):
        self.name = name
        self.transitions = {k: set(v) for k, v in transitions.items()}

    def allowed(self, current):
        return self.transitions.get(current, set())

    def can(self, current, new):
        return new in self.allowed(current)

    def check(self, current, new):
        if not self.can(current, new):
            raise DomainError(f"A {self.name} can't move from {current} to {new}.")
