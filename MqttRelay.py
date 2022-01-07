from gmqtt import Client as MQTTClient
import logging


logger = logging.getLogger("MQTT_MicrotempGateway")

def on_connect(client, flags, rc, properties):
    logger.info(f"{client} connected to MQTT broker.")

def on_disconnect(client, packet, exc=None):
    logger.info(f"{client} disconnected from MQTT broker.")

def on_subscribe(client, mid, qos, properties):
    # Callback when subscribing.
    pass


async def sub_client(broker, port, username, password) -> MQTTClient:
    client = MQTTClient("client-id-sub")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    client.set_auth_credentials(username, password)
    await client.connect(broker, port)

    return client

async def pub_client(broker, port, username, password) -> MQTTClient:
    client = MQTTClient("client-id-pub")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    client.set_auth_credentials(username, password)
    await client.connect(broker, port)

    return client