"""MAIT Bridge: the Doovit half of the MAIT radio bridge (stub)."""


def main():
    # Imported here so the schema exporters and tests don't need the device
    # runtime's gRPC stack.
    from pydoover.docker import run_app

    from .application import MaitBridgeApplication

    run_app(MaitBridgeApplication())
