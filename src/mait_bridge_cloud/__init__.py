from pydoover.processor import run_app

from .application import MaitBridgeCloudApplication


def handler(event, context):
    """Lambda handler entry point."""
    return run_app(
        MaitBridgeCloudApplication(),
        event,
        context,
    )
