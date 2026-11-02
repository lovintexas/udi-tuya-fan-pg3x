import threading
import time


class ConfigSync:
    def __init__(self):
        self.condition = threading.Condition()
        self.write_lock = threading.Lock()
        self.params = {}
        self.ready = False
        self.generation = 0

    def update(self, params):
        if not isinstance(params, dict):
            raise ValueError("Invalid PG3x custom parameters")

        with self.condition:
            self.params = dict(params)
            self.generation += 1
            self.condition.notify_all()

    def mark_ready(self):
        with self.condition:
            self.ready = True
            self.condition.notify_all()

    def snapshot(self, timeout=10):
        deadline = time.monotonic() + timeout

        with self.condition:
            while not self.ready:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        "Initial PG3x configuration not received"
                    )
                self.condition.wait(remaining)

            return dict(self.params)

    def save(self, polyglot, params, timeout=10):
        if not isinstance(params, dict):
            raise ValueError("Invalid PG3x custom parameters")

        with self.write_lock:
            self.snapshot(timeout=timeout)

            with self.condition:
                starting_generation = self.generation

            polyglot.send(
                {
                    "set": [
                        {"key": "customparams", "value": params}
                    ]
                },
                "custom"
            )

            # Request a database readback rather than relying on
            # the unsolicited response to the SET command.
            polyglot.send({"getAll": {}}, "custom")

            deadline = time.monotonic() + timeout

            with self.condition:
                while True:
                    if (
                        self.generation > starting_generation
                        and self.params == params
                    ):
                        return dict(self.params)

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            "PG3x did not confirm the configuration save"
                        )

                    self.condition.wait(remaining)
