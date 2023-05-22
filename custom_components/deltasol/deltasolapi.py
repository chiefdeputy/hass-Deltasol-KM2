"""
Gets sensor data from Resol KM2, DL2/DL3, VBus/LAN, VBus/USB using api.
Author: dm82m
https://github.com/dm82m/hass-Deltasol-KM2
"""
import datetime
import re
from collections import namedtuple

from .const import (
    _LOGGER,
    SETUP_RETRY_COUNT,
    SETUP_RETRY_PERIOD
)

import aiohttp
import asyncio
from homeassistant.exceptions import IntegrationError

DeltasolEndpoint = namedtuple('DeltasolEndpoint', 'name, value, unit, description, bus_dest, bus_src')

class DeltasolApi(object):
    """ Wrapper class for Resol KM2, DL2/DL3, VBus/LAN, VBus/USB. """

    def __init__(self, username, password, host, api_key, websession):
        self.data = None
        self.host = host
        self.username = username
        self.password = password
        self.api_key = api_key
        self.websession = websession
        self.product = None

    def __parse_data(self, response):
        data = {}

        iHeader = 0
        for header in response["headers"]:
            _LOGGER.debug(f"Found header[{iHeader}] now parsing it ...")
            iField = 0
            for field in response["headers"][iHeader]["fields"]:
                value = response["headersets"][0]["packets"][iHeader]["field_values"][iField]["raw_value"]
                if isinstance(value, float):
                    value = round(value, 2)
                unique_id = header["id"] + "__" + field["id"]
                data[unique_id] = DeltasolEndpoint(
                    name=field["name"].replace(" ", "_").lower(),
                    value=value,
                    unit=field["unit"].strip(),
                    description=header["description"],
                    bus_dest=header["destination_name"],
                    bus_src=header["source_name"])
                iField += 1
            iHeader +=1

        return data

    async def detect_product(self):
        if self.product is not None:
            return self.product
            
        try:
            url = f"http://{self.host}/cgi-bin/get_resol_device_information"
            _LOGGER.info(f"Auto detecting Resol product from {url}")
            async with self.websession.get(url) as response:
                if(response.status  == 200):
                    _LOGGER.debug(f"response: {response.text}")
                    text = await response.text()
                    matches = re.search(r'product\s=\s["](.*?)["]', text)
                    if matches:
                        self.product = matches.group(1).lower()
                        _LOGGER.info(f"Detected Resol product: {self.product}")
                    else:
                        error = "Your device was reachable but we could not correctly detect it, please file an issue at: https://github.com/dm82m/hass-Deltasol-KM2/issues/new/choose"
                        _LOGGER.error(error)
                        raise IntegrationError(error)
                else:
                    error = "Are you sure you entered the correct address of the Resol KM2/DL2/DL3 device? Please re-check and if the issue still persists, please file an issue here: https://github.com/dm82m/hass-Deltasol-KM2/issues/new/choose"
                    _LOGGER.error(error)
                    raise IntegrationError(error)
        except aiohttp.ClientConnectorError:
            _LOGGER.warning("Could not reach %s.", self.host)
        except aiohttp.ClientError as e:
            error = f"Error detecting Resol product - {e}, please file an issue at: https://github.com/dm82m/hass-Deltasol-KM2/issues/new/choose"
            _LOGGER.error(error)
            raise IntegrationError(error)
            
        return self.product


    async def fetch_data(self):
        """ Use api to get data """
        retries = 0
        while self.product is None and retries < SETUP_RETRY_COUNT:
            retries += 1
            await self.detect_product()
            await asyncio.sleep(SETUP_RETRY_PERIOD)
        if self.product is None:
            raise IntegrationError("Could not identify Resol product. Most likely due to a connection error.")

        try:
            response = {}
            if(self.product == 'km2'):
                response = await self.fetch_data_km2()
            elif(self.product == 'dl2' or product == 'dl3'):
                response = await self.fetch_data_dlx()
            else:
                error = f"We detected your Resol product as {self.product} and this product is currently not supported. If you want you can file an issue to support this device here: https://github.com/dm82m/hass-Deltasol-KM2/issues/new/choose"
                _LOGGER.error(error)
                raise IntegrationError(error)

            return self.__parse_data(response)

        except IntegrationError as error:
            raise error


    async def fetch_data_km2(self):
        _LOGGER.debug("Retrieving data from km2")
        
        result = {}
        
        url = f"http://{self.host}/cgi-bin/resol-webservice"
        _LOGGER.debug(f"KM2 requesting sensor data url {url}")
                
        try:
            payload = [{'id': '1','jsonrpc': '2.0','method': 'login','params': {'username': '" + self.username + "','password': '" + self.password + "'}}]
            async with self.websession.post(url, json=payload) as response:
                data = await response.json()
                authId = data[0]['result']['authId']
                
            
            payload = [{'id': '1','jsonrpc': '2.0','method': 'dataGetCurrentData','params': {'authId': '" + authId + "'}}]
            async with self.websession.post(url, json=payload) as response:
                data = await response.json()
                _LOGGER.debug(f"KM2 response: {data}")
                result = data[0]["result"]
        except aiohttp.ClientConnectorError as e:
            _LOGGER.warning("Could not fetch data from KM2: %s", e)
        except aiohttp.ClientError:
            error = "Please re-check your username and password in your configuration!"
            _LOGGER.error(error)
            raise IntegrationError(error)
        
        return result


    async def fetch_data_dlx(self):
        _LOGGER.debug("Retrieving data from dlx")
        
        result = {}

        url = f"http://{self.host}/dlx/download/live"
        debugMessage = f"DLX requesting sensor data url {url}"
        
        if self.username is not None and self.password is not None:
            auth = f"?sessionAuthUsername={self.username}&sessionAuthPassword={self.password}"
            filter = f"&filter={self.api_key}" if self.api_key else ""
            url = f"{url}{auth}{filter}"
            debugMessage = f"DLX requesting sensor data url {url.replace(self.password, '***')}"
            
        _LOGGER.debug(debugMessage)
        
        try:
            async with self.websession.get(url) as response:
                if(response.status == 200):
                    result = await response.json()
                else:
                    error = "Please re-check your username and password in your configuration!"
                    _LOGGER.error(error)
                    raise IntegrationError(error)
                
            _LOGGER.debug(f"DLX response: {result}")
        except aiohttp.ClientConnectorError as e:
            _LOGGER.warning("Could not fetch data from DLx: %s", e)
        except aiohttp.ClientError:
            error = "Please re-check your username and password in your configuration!"
            _LOGGER.error(error)
            raise IntegrationError(error)

        return result
