"""
Peek one message from the training-data-ready topic (local / integration debugging).

Requires a subscription that actually exists in your Service Bus namespace. Project docs
use subscription name `orchestrator-sub` on topic `training-data-ready`; the name is
not fixed in code—set TRAINING_DATA_READY_SUBSCRIPTION to match Azure.

Connection string: SB_CONN or TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING (same as
local.settings.json).
"""
import json
import os
import sys

from azure.servicebus import ServiceBusClient

CONN = os.environ.get("SB_CONN") or os.environ.get(
    "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING"
)
TOPIC = os.environ.get("TRAINING_DATA_READY_TOPIC", "training-data-ready")
SUBSCRIPTION = os.environ.get("TRAINING_DATA_READY_SUBSCRIPTION", "orchestrator-sub")

if not CONN:
    print(
        "Set SB_CONN or TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING "
        "(copy from local.settings.json).",
        file=sys.stderr,
    )
    sys.exit(1)

with ServiceBusClient.from_connection_string(CONN) as client:
    receiver = client.get_subscription_receiver(
        topic_name=TOPIC,
        subscription_name=SUBSCRIPTION,
        max_wait_time=30,
    )
    with receiver:
        for msg in receiver:
            print("AppProps:", msg.application_properties)
            body = json.loads(str(msg))
            print("Body keys:", list(body.keys()))
            print("Data location:", body.get("data_location"))
            receiver.complete_message(msg)
            break
