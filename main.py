import asyncio
from MqttRelay import pub_client, sub_client
import MqttRelay
import Microtemp
from dacite import from_dict
import json
import time
from typing import Dict, List
import logging
from conf import hass_config_prefix, microtemp_password, microtemp_username, mqtt_boker, mqtt_password, mqtt_port, mqtt_username

logging_level = "INFO"
logger = logging.getLogger("MQTT_MicrotempGateway")
logger.setLevel(logging_level)

ch = logging.StreamHandler()
ch.setLevel(logging_level)
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
ch.setFormatter(log_format)
logger.addHandler(ch)





# Different types of registers to keep track on registered thermostats and their associated topics.
thermostats: Dict[str, Microtemp.Thermostat] = {}
mqtt_subsriptions: List[str] = []
mqtt_availability_topics: Dict[str, str] = {}
mqtt_command_topics: Dict[str, str] = {}
mqtt_state_topics: Dict[str, str] = {}


async def get_all_thermostats(api_con: Microtemp.ApiConnection):
    logger.debug("Fetching thermostats info from API.")
    response = await api_con.get_thermostats()
    for i in response:
        thermo = from_dict(data_class=Microtemp.Thermostat, data=i)
        thermostats[i['SerialNumber']] = thermo
        logger.debug(f"Found thermostat with serialnumber {i['SerialNumber']}. Thermostat added to registery.")


async def mqtt_publish_configs(mqtt_con: MqttRelay.MQTTClient, mqtt_sub: MqttRelay.MQTTClient):
    for item in thermostats:

        topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/config"
        availability_topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/available"
        state_topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/state"
        command_topic = f"{hass_config_prefix}/climate/micromatic_thermostat_{thermostats[item].SerialNumber}/set"

        mqtt_availability_topics[thermostats[item].SerialNumber] = availability_topic
        mqtt_state_topics[thermostats[item].SerialNumber] = state_topic
        mqtt_command_topics[thermostats[item].SerialNumber] = command_topic

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

        logger.info(f"Publishing thermostat config to mqtt topic {topic}")
        logger.debug(f"Payload:\n{payload}")
        mqtt_con.publish(topic, payload, qos=0, retain=True)
        mqtt_sub.subscribe(command_topic)

async def publish_availability(mqtt_con: MqttRelay.MQTTClient, state: str, serialnumber: str):
        if serialnumber == "all":
            for key in mqtt_availability_topics:
                topic = mqtt_availability_topics[key]
                logger.debug(f"Published availability mqtt message to topic {topic}. Availability state: {state}")
                mqtt_con.publish(topic, payload=state, qos=0)

        else:
            topic = mqtt_availability_topics[serialnumber]
            logger.debug(f"Published availability mqtt message to topic {topic}. Availability state: {state}")
            mqtt_con.publish(topic, payload=state, qos=0)


async def update_publish_state(mqtt_con: MqttRelay.MQTTClient, serialnumber: str):
    if serialnumber == "all":
        for key in mqtt_state_topics:
                topic = mqtt_state_topics[key]
                thermostat = thermostats[key]

                hass_state = await thermostat.to_hass_state()
                logger.debug(f"Published updated state to mqtt topic {topic}. New state:\n{hass_state}")
                mqtt_con.publish(topic, payload=hass_state, qos=0)
    else:
        topic = mqtt_state_topics[serialnumber]
        thermostat = thermostats[serialnumber]

        hass_state = await thermostat.to_hass_state()
        logger.debug(f"Published updated state to mqtt topic {topic}. New state:\n{hass_state}")
        mqtt_con.publish(topic, payload=hass_state, qos=0, retain=True)

async def handle_websocket_msg(message, mqtt_con: MqttRelay.MQTTClient):
    message = json.loads(message)
    if not message:
        return
    for item in message['M']:
        if isinstance(item, str):
            item = json.loads(item)
            if not item['Thermostat']:
                return

            thermo = from_dict(data_class=Microtemp.Thermostat, data=item['Thermostat'])
            thermostats[item['Thermostat']['SerialNumber']] = thermo
            logger.debug(f"Recieved incoming message on websocket for thermostat with serial number {thermo.SerialNumber}.")

            await update_publish_state(mqtt_con, item['Thermostat']['SerialNumber'])
            await publish_availability(mqtt_con, "online", item['Thermostat']['SerialNumber'])


async def handle_mqtt_message(client, topic, payload, qos, properties):
    # Handle incoming MQTT messages. Change Thermostat change-flag to True.

    logger.debug(f"Recieved message on topic {topic}:\n{payload}")

    modes = {
            "auto": 1,
            "heat": 3,
            "off": 5
        }
    
    payload = json.loads(payload)
    serialnumber = payload['unique_id']
    
    thermostat = thermostats[serialnumber]

    if 'target_temperature' in payload:
        thermostat.ManuelFloorTemperature = int(payload['target_temperature'] * 100)
        thermostat.ManuelRoomTemperature = int(payload['target_temperature'] * 100)
        
    thermostat.RegulationMode = modes[payload['mode']]
    thermostat.isChanged = True

    
async def update_state_loop(api_con: Microtemp.ApiConnection):
    # Checks if any of the thermostats has updated state. And publish new state to MQTT.
    while True:
        for key in thermostats:
            thermostat = thermostats[key]

            if thermostat.isChanged:
                thermostat.isChanged = False
                await api_con.change_state(thermostat)
                
        
        await asyncio.sleep(0.4)

async def main():
    subClient = await sub_client(mqtt_boker, mqtt_port, mqtt_username, mqtt_password)
    pubClient = await pub_client(mqtt_boker, mqtt_port, mqtt_username, mqtt_password)

    microtemp_api_con = Microtemp.ApiConnection(username=microtemp_username, password=microtemp_password)
    microtemp_api_con.authenticate()

    microtemp_websocket = Microtemp.Websocket(microtemp_api_con, pubClient)

    await get_all_thermostats(microtemp_api_con)
    await mqtt_publish_configs(pubClient, subClient)
    
    time.sleep(2)
    await update_publish_state(pubClient, "all")
    subClient.on_message = handle_mqtt_message

    
    mqtt_task = asyncio.create_task(update_state_loop(microtemp_api_con), name="mqtt_task")
    websocket_task = asyncio.create_task(microtemp_websocket.connect_await_incoming(handle_websocket_msg), name="websocket_task")

    await asyncio.gather(mqtt_task, websocket_task, return_exceptions=True)



if __name__ == "__main__":

    asyncio.run(main(), debug=False)