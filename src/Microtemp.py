from __future__ import annotations
import json
import time
from dataclasses import asdict, dataclass, field
import requests
import datetime
import logging
import websockets.client as websocket_client
import random
from math import floor
from urllib.parse import quote
from typing import Callable, Dict
import asyncio
from dacite import from_dict


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from MqttRelay import MqttConnector


logger = logging.getLogger("MQTT_MicromaticGateway")


@dataclass
class Thermostat:
    SerialNumber: str
    GroupName: str
    GroupId: int
    TemperatureRoom: int
    TemperatureFloor: int
    SensorApplication: int
    Address: str
    SateliteType: int
    ErrorCode: int
    RelayOn2Days: int
    RelayOn30Days: int
    RelayOn365Days: int
    RegulationMode: int
    VacationBeginDay: str
    VacationEndDay: str
    VacationBeginTime: str
    VacationEndTime: str
    VacationTemperature: int
    ComfortTime: str
    ManuelRoomTemperature: int
    ManuelFloorTemperature: int
    ManuelRegulator: int
    FrostRoomTemperature: int
    FrostFloorTemperature: int
    LosEnabled: bool
    LosTempAuto: int
    LosTempFrost: int
    IdentifyThermo: bool
    UtcOffset: int
    isChanged: bool = field(default=False, repr=False, init=False)
    Schedule: dict = field(default_factory=dict)

    async def to_hass_state(self):
        modes = {
            1: "auto",
            3: "heat",
            5: "off"
        }
        mode = modes[self.RegulationMode]
        target_temp = self.ManuelRoomTemperature / 100
        curr_temp = self.TemperatureRoom / 100
        event_on_previous_day = True

        if mode == "auto":
            current_day = datetime.datetime.today().weekday()
            for item in self.Schedule['Days'][current_day]["Events"]:
                if not item["Active"]:
                    continue

                now_time = datetime.datetime.now()
                schedule_time = datetime.datetime.strptime(
                    item['Clock'], '%H:%M:%S')
                schedule_time = schedule_time.replace(
                    day=now_time.day, month=now_time.month, year=now_time.year)

                if now_time >= schedule_time:
                    target_temp = self.Schedule['ComfortTemperatureRoom'] / \
                        100 if item['EventIsComfortTemp'] else self.Schedule['SetbackTemperatureRoom'] / 100
                    event_on_previous_day = False


            if event_on_previous_day:    
                day = current_day - 1 if current_day - 1 >= 0 else 6
                for item in reversed(self.Schedule['Days'][day]["Events"]):
                    if not item["Active"]:
                        continue

                    target_temp = self.Schedule['ComfortTemperatureRoom'] / \
                        100 if item['EventIsComfortTemp'] else self.Schedule['SetbackTemperatureRoom'] / 100
                    break
                    

        new_state = {
            "mode": mode,
            "target_temperature": target_temp,
            "current_temperature": curr_temp
        }

        return json.dumps(new_state)

    def as_dict(self):
        instance = asdict(self)
        instance.pop("isChanged")

        return instance


class ApiConnection:

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self.connected = False
        self._headers = {
            "Accept": "application/json, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "nb-NO,nb;q=0.9,no-NO;q=0.8,no;q=0.6,nn-NO;q=0.5,nn;q=0.4,en-US;q=0.3,en",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "application/json; charset=utf-8"
        }

    def authenticate(self):
        logger.debug("Authenticating to Micromatic API.")

        auth_url: str = "https://min.microtemp.no/api/authenticate/user"
        payload: dict = {
            "Application": 0,
            "Email": self.username,
            "Password": self.password
        }

        response = requests.post(auth_url, data=json.dumps(
            payload), headers=self._headers)
        json_response = response.json()

        if response.status_code != 200 or json_response['ErrorCode'] != 0:
            raise RuntimeError("Microtemp API authentication failed.")

        self.session_id = json_response['SessionId']
        self.new_account = json_response['NewAccount']
        self.error_code = json_response['ErrorCode']
        self.role_type = json_response['RoleType']
        self.customer_id = json_response['CustomerId']
        self.email = self.username
        self.language = json_response['Language']
        self.accepted_toc = json_response['AcceptedTOC']
        self.connected = True

        logger.info("Connected to Micromatic API.")

    async def get(self, url: str, params: dict = None) -> dict:
        """
            Async method for processing GET requests to the Microtemp API.
            If not authenticated there will be made one attempt to reauthenticate.
            Will raise RuntimeError in the following scenarios:
                - Authentication error (401) twice
                - Unsuccessful GET request (if HTTPerror above 400) after attempting to reauthenticate

            Parameters:
                - url [string]
                - params [dict] HTTP get parameters

            return: HTTP reponse [dict] if get request was successful else RuntimeError is raised
        """

        logger.debug("Sending GET request to Micromatic API.\nURL: %s\nParams: %s", url, params)
        response = requests.get(url=url, params=params, headers=self._headers)

        if not response.ok:
            if response.status_code == 401:
                self.authenticate()
                response = requests.get(
                    url=url, params=params, headers=self._headers)
                if not response.ok:
                    raise RuntimeError(
                        f"Unable to process GET request to {response.url}. \n {response.status_code} {response.reason} \n {response.text}")

            else:
                raise RuntimeError(
                    f"Unable to process GET request to {response.url}. \n {response.status_code} {response.reason} \n {response.text}")

        return response.json()

    async def post(self, url: str, payload: dict, params: dict = None) -> dict:
        """
            Async method for processing POST requests to the Microtemp API.
            If not authenticated there will be made one attempt to reauthenticate.
            Will raise RuntimeError in the following scenarios:
                - Authentication error (401) twice
                - Unsuccessful POST request (if HTTPerror above 400) after attempting to reauthenticate

            Parameters:
                - url [string]
                - payload [dict] - POST request payload

            return: HTTP reponse [dict] if POST request was successful else RuntimeError is raised
        """

        logger.debug("Sending POST request to Micromatic API.\nURL: %s\nParams: %s\nPayload: %s", url, params, payload)

        response = requests.post(
            url=url, data=payload, headers=self._headers, params=params)

        if not response.ok:
            if response.status_code == 401:
                self.authenticate()
                response = requests.post(
                    url=url, data=payload, headers=self._headers, params=params)
                if not response.ok:
                    raise RuntimeError(
                        f"Unable to process POST request to {response.url}. \n {response.status_code} {response.reason} \n {response.text}")

            else:
                raise RuntimeError(
                    f"Unable to process POST request to {response.url}. \n {response.status_code} {response.reason} \n {response.text}")

        return response.json()

    async def negotiate(self) -> dict:
        """
            Method to obtain connection token for the websocket interface.
            Returns dictionary with websocket connection details (including connection token) that will be used to initiate
            websocket instance.
        """
        url = "https://min.microtemp.no/gatewaynotification/negotiate"
        params = {
            "clientProtocol": 2.1,
            "_": round(time.time())
        }

        return await self.get(url, params)

    async def change_state(self, thermostat: Thermostat):
        serialnumber = thermostat.SerialNumber
        payload = json.dumps(thermostat.as_dict())
        url = "https://min.microtemp.no/api/thermostat/change"

        params = {
            "sessionid": self.session_id,
            "serialnumber": serialnumber
        }

        logger.debug("Sending POST request to Micromatic API.\nURL: %s\nParams: %s\nPayload: %s", url, params, payload)
        response = requests.post(
            url=url, data=payload, headers=self._headers, params=params)

        if not response.ok:
            if response.status_code == 401:
                self.authenticate()
                params['sessionid'] = self.session_id
                response = requests.post(
                    url=url, data=payload, headers=self._headers, params=params)
                if not response.ok:
                    raise RuntimeError(
                        f"Unable to process POST request to {response.url}. \n {response.status_code} {response.reason} \n {response.text}")

            else:
                raise RuntimeError(
                    f"Unable to process POST request to {response.url}. \n {response.status_code} {response.reason} \n {response.text}")

        return response.json()

    async def get_thermostats(self) -> list:
        """
            Method to get information of the thermostats.
        """
        thermostats: list = []
        url = "https://min.microtemp.no/api/thermostats"
        params = {
            "sessionid": self.session_id
        }

        response = await self.get(url, params)

        for i in response['Groups']:
            if not i['Thermostats']:
                continue

            for ii in i['Thermostats']:
                thermostats.append(ii)
                
        return thermostats
    
    async def get_all_thermostats(self, thermostats: Dict[str, Thermostat]):
        logger.debug("Fetching thermostats info from API.")
        response = await self.get_thermostats()
        for i in response:
            thermo = from_dict(data_class=Thermostat, data=i)
            thermostats[i['SerialNumber']] = thermo
            logger.debug('Found thermostat with serialnumber %s. Thermostat added to registery.', i["SerialNumber"])


class Websocket:
    def __init__(self, api_con: ApiConnection, mqtt_con: MqttConnector):
        self.api_con = api_con
        self.mqtt_con = mqtt_con
        self.reconnect_attempts: int = 0
        self.last_reconnect_attempt: datetime.datetime = datetime.datetime.now()

    async def connect_await_incoming(self, handle_websocket_msg: Callable):
        websocket_details = await self.api_con.negotiate()
        connection_token = websocket_details['ConnectionToken']
        quoted_token = quote(connection_token)
        session_id = self.api_con.session_id
        tid = floor(random.random() * 10) + 1
        url = f"wss://min.microtemp.no/gatewaynotification/connect?transport=webSockets&clientProtocol=2.1&connectionToken={quoted_token}&tid={tid}"

        async with websocket_client.connect(url) as websocket:
            params = {
                "transport": "webSockets",
                "clientProtocol": 2.1,
                "connectionToken": connection_token
            }

            # Notify server to start sending notifications on the websocket connection.
            await self.api_con.get("https://min.microtemp.no/gatewaynotification/start", params)

            # Authenticate the client on the websocket by sending the session ID.
            await websocket.send(session_id)
            logger.debug("Connected to websocket url %s", url)
            logger.info("Connected to Micromatic websocket.")
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), 900)
                    await handle_websocket_msg(message, self.mqtt_con)
                except asyncio.exceptions.TimeoutError:
                    if datetime.datetime.now() - self.last_reconnect_attempt <= datetime.timedelta(minutes=5):
                        self.reconnect_attempts += 1
                        self.last_reconnect_attempt = datetime.datetime.now()
                    else:
                        # Reset the attempt counter if more than 5 mins since last timeout.
                        self.reconnect_attempts = 1
                        self.last_reconnect_attempt = datetime.datetime.now()


                    if self.reconnect_attempts > 5:
                        logger.info("Unable to reconnect to websocket. Closing...")
                        loop = asyncio.get_event_loop()
                        await loop.shutdown_default_executor()
                        await loop.stop()
                        
                    logger.info("Websocket connection timed out. Attempting to reconnect. Attempts: %d", self.reconnect_attempts)
                    asyncio.create_task(self.connect_await_incoming(handle_websocket_msg), name="websocket_task")
                    break

    
