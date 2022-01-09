ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /usr/src/hass_micromatic_gateway

COPY ./src .
RUN apk update && apk upgrade
RUN apk add python3 && apk add py3-pip
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY run.sh /
RUN chmod a+x /run.sh

CMD ["/run.sh"]
