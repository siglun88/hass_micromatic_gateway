from gmqtt import Client as MQTTClient
import logging
from Microtemp import Thermostat
from conf import hass_config_prefix
from typing import Callable, Dict, List
import json


# Guess only 1 client is needed as combinded pub/sub, will fix later....

logger = logging.getLogger("MQTT_MicrotempGateway")

class MqttConnector:

    def __init__(self, broker: str, port: str, username: str, password: str):
        self.broker = broker
        self.port = port
        self.username = username
        self.password = password
        self.client = None
        self.subsriptions: List[str] = []
        self.availability_topics: Dict[str, str] = {}
        self.command_topics: Dict[str, str] = {}
        self.state_topics: Dict[str, str] = {}

    def on_connect(self, client, flags, rc, properties):
        logger.info("Connected to MQTT broker.")

    def on_disconnect(self, client, packet, exc=None):
        logger.info("Disconnected from MQTT broker.")
        self.publish_availability("offline", "all")

    def on_subscribe(self, client, mid, qos, properties):
        # Callback when subscribing.
        pass

    async def connect(self, on_message: Callable):
        self.client = MQTTClient("client-id-pub")

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = on_message

        self.client.set_auth_credentials(self.username, self.password)
        await self.client.connect(self.broker, self.port)
        

        return self
    
    async def mqtt_publish_configs(self, thermostats: Thermostat):

        for item in thermostats:

            topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/config"
            availability_topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/available"
            state_topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/state"
            command_topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/set"

            self.availability_topics[thermostats[item].SerialNumber] = availability_topic
            self.state_topics[thermostats[item].SerialNumber] = state_topic
            self.command_topics[thermostats[item].SerialNumber] = command_topic

            payload = {
                "availability_topic": f"{availability_topic}",
                "current_temperature_template": "{{ value_json.current_temperature }}",
                "current_temperature_topic": f"{state_topic}",
                "device": {
                    "identifiers": f"{thermostats[item].SerialNumber}",
                    "manufacturer": "Micromatic",
                    "name": f"Micromatic Thermostat {thermostats[item].SerialNumber}",
                    "model": "MSD4"
                },
                "initial": 22,
                "icon": "mdi:thermostat",
                "max_temp": 32.5,
                "min_temp": 12.0,
                "mode_command_topic": f"{command_topic}",
                "mode_command_template": f"{{% set command = {{\"unique_id\": \"{thermostats[item].SerialNumber}\", \"mode\": value }} %}} {{{{ command|to_json }}}}",
                "mode_state_template": "{{ value_json.mode }}",
                "mode_state_topic": f"{state_topic}",
                "modes": ["auto", "heat", "off"],
                "object_id": f"micromatic_thermostat_{thermostats[item].SerialNumber}",
                "precicion": 0.5,
                "temperature_command_topic": f"{command_topic}",
                "temperature_command_template": f"{{% set command = {{\"unique_id\": \"{thermostats[item].SerialNumber}\", \"target_temperature\": value | round(1), \"mode\": \"heat\" }} %}} {{{{ command|to_json }}}}",
                "temperature_state_template": "{{ value_json.target_temperature }}",
                "temperature_state_topic": f"{state_topic}",
                "temperature_unit": "c",
                "temp_step": 0.5,
                "unique_id": f"{thermostats[item].SerialNumber}",
                "name": f"Micromatic Thermostat {thermostats[item].GroupName}"
            }
            payload = json.dumps(payload)

            logger.info("Publishing thermostat config to mqtt topic %s", topic)
            logger.debug("Payload:\n%s", payload)
            self.client.publish(topic, payload, qos=0, retain=True)
            self.client.subscribe(command_topic)

    async def update_publish_state(self, serialnumber: str, thermostats: Dict[str, Thermostat]):
        if serialnumber == "all":
            for key in self.state_topics:
                topic = self.state_topics[key]
                thermostat = thermostats[key]

                hass_state = await thermostat.to_hass_state()
                logger.debug("Published updated state to mqtt topic %s. New state:\n%s", topic, hass_state)
                self.client.publish(topic, payload=hass_state, qos=0)
        else:
            topic = self.state_topics[serialnumber]
            thermostat = thermostats[serialnumber]

            hass_state = await thermostat.to_hass_state()
            logger.debug("Published updated state to mqtt topic %s. New state:\n%s", topic, hass_state)
            self.client.publish(topic, payload=hass_state, qos=0, retain=True)


    async def publish_availability(self, state: str, serialnumber: str):
        if serialnumber == "all":
            for key in self.availability_topics:
                topic = self.availability_topics[key]
                logger.debug("Published availability mqtt message to topic %s. Availability state: %s", topic, state)
                self.client.publish(topic, payload=state, qos=0)

        else:
            topic = self.availability_topics[serialnumber]
            logger.debug("Published availability mqtt message to topic %s. Availability state: %s", topic, state)
            self.client.publish(topic, payload=state, qos=0)


