#!/usr/bin/with-contenv bashio

MQTT_BROKER=$(bashio::config 'mqtt_broker_address')
MQTT_PORT=$(bashio::config 'mqtt_broker_port')
MQTT_USERNAME=$(bashio::config 'mqtt_username')
MQTT_PASSWORD=$(bashio::config 'mqtt_password')
CONFIG_PREFIX=$(bashio::config 'mqtt_config_topic_prefix')
MICROMATIC_USERNAME=$(bashio::config 'micromatic_username')
MICROMATIC_PASSWORD=$(bashio::config 'micromatic_password')

python3 /usr/src/hass_micromatic_gateway/main.py --mqtt_broker ${MQTT_BROKER} --mqtt_port ${MQTT_PORT} --mqtt_username ${MQTT_USERNAME} --mqtt_password ${MQTT_PASSWORD} --config_prefix ${CONFIG_PREFIX} --micromatic_username ${MICROMATIC_USERNAME} --micromatic_password ${MICROMATIC_PASSWORD}