import asyncio
import MqttRelay
import Microtemp
from dacite import from_dict
import json
import time
from typing import Dict
import logging
import argparse

logging_level = "INFO"
logger = logging.getLogger("MQTT_MicromaticGateway")
logger.setLevel(logging_level)

ch = logging.StreamHandler()
ch.setLevel(logging_level)
log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s') 
ch.setFormatter(log_format)
logger.addHandler(ch)


# Thermostat registery. Could probably be a part of the Thermostat dataclass...
thermostats: Dict[str, Microtemp.Thermostat] = {}

async def handle_websocket_msg(message, mqtt_con: MqttRelay.MqttConnector):
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
            logger.debug("Recieved incoming message on websocket for thermostat with serial number %s.", thermo.SerialNumber)

            await mqtt_con.update_publish_state(item['Thermostat']['SerialNumber'], thermostats)
            await mqtt_con.publish_availability("online", item['Thermostat']['SerialNumber'])


async def handle_mqtt_message(client, topic, payload, qos, properties):
    # Handle incoming MQTT messages. Change Thermostat change-flag to True.

    logger.debug("Recieved message on topic %s:\n%s", topic, payload)

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
    # Checks if any of the thermostats has updated state. And publish new state to MQTT

    while True:
        for key in thermostats:
            thermostat = thermostats[key]

            if thermostat.isChanged:
                thermostat.isChanged = False
                await api_con.change_state(thermostat)
                
        
        await asyncio.sleep(0.4)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mqtt_broker", help="IP address or hostname to MQTT broker", required=True)
    parser.add_argument("--mqtt_port", help="MQTT broker port", required=True)
    parser.add_argument("--mqtt_username", help="MQTT username", required=True)
    parser.add_argument("--mqtt_password", help="MQTT password", required=True)
    parser.add_argument("--config_prefix", help="MQTT config prefix for Home Assistant", required=True, default="homeassistant")
    parser.add_argument("--micromatic_username", help="Micromatic username", required=True)
    parser.add_argument("--micromatic_password", help="Micromatic password", required=True)
    args = parser.parse_args()
    
    mqtt_client = MqttRelay.MqttConnector(args.mqtt_broker, args.mqtt_port, args.mqtt_username, args.mqtt_password, args.config_prefix)
    await mqtt_client.connect(on_message=handle_mqtt_message)

    microtemp_api_con = Microtemp.ApiConnection(username=args.micromatic_username, password=args.micromatic_password)
    microtemp_api_con.authenticate()

    microtemp_websocket = Microtemp.Websocket(microtemp_api_con, mqtt_client)

    await microtemp_api_con.get_all_thermostats(thermostats)
    await mqtt_client.mqtt_publish_configs(thermostats)
    
    time.sleep(2)
    await mqtt_client.publish_availability("online", "all")
    await mqtt_client.update_publish_state("all", thermostats)


    
    mqtt_task = asyncio.create_task(update_state_loop(microtemp_api_con), name="mqtt_task")
    websocket_task = asyncio.create_task(microtemp_websocket.connect_await_incoming(handle_websocket_msg), name="websocket_task")

    await asyncio.gather(mqtt_task, websocket_task)



if __name__ == "__main__":

    asyncio.run(main(), debug=False)

