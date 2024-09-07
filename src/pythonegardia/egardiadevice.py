"""
Egardia / Woonveilig alarm object
"""
import logging

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES_TO_IGNORE = ["Remote Controller", "Remote Keypad", "Keypad"]
SUPPORTED_VERSIONS = ["WV-1716", "GATE-01","GATE-02", "GATE-03", "GATE-04"]
UNAUTHORIZED_MESSAGES = ["Unauthorized", "Access Denied"]
GATE03_STATES_MAPPING = {'FULL ARM':'ARM','HOME ARM 1':'HOME','HOME ARM 2':'HOME','HOME ARM 3':'HOME','DISARM':'DISARM'}

class UnauthorizedError(Exception):
    """
    Unauthorized Error
    """
    def __init__(self, value):
        super(self.__class__, self).__init__(value)
        self.value = value
    def __str__(self):
        return repr(self.value)

class VersionError(Exception):
    """
    Version Error
    """
    def __init__(self, value):
        super(self.__class__, self).__init__(value)
        self.value = value
    def __str__(self):
        return repr(self.value)

class EgardiaDevice(object):
    """
    Representation of an Egardia Device
    """
    def __init__(self, host, port, username, password, state, version):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._status = state
        self._version = version.upper()
        if self._version not in SUPPORTED_VERSIONS:
            raise VersionError('Egardia device version '+self._version+' is unsupported.')
        else: 
            self._sensors = self.getsensors()
            self.update()

    def state(self):
        """Return _status"""
        return self._status

    def update(self):
        """Update the alarm status."""
        self._status = self.getstate()

    def statusunauthorized(self, text):
        """Check for unautorized messages in a given text."""
        for msg in UNAUTHORIZED_MESSAGES:
            if msg in text:
                return True
        return False

    def dorequestwithretry(self, mode, service, maxretries=1, payload=None):
        """Do a request and retry."""
        for i in range(maxretries+1):
            try:
                req = self.dorequest(mode, service, payload)
            except:
                raise
            statustext = req.text
            i = i + 1
            if not self.statusunauthorized(statustext):
                break
              
        if self.statusunauthorized(statustext):
            raise UnauthorizedError('Unable to login to system using the credentials provided')
        else:
            return statustext

    def getstate(self):
        """Get the status from the alarm panel"""
        import requests
        #Get status
        statustext = self.dorequestwithretry('get','panelCondGet')

        if self._version in ["GATE-01", "GATE-02"]:
            ind1 = statustext.find('mode_a1 : "')
            numcharstoskip = 11
        elif self._version == "GATE-03":
            ind1 = statustext.find('"mode_a1" : "')
            numcharstoskip = 13
        elif self._version == "WV-1716":
            ind1 = statustext.find('mode_st : "')
            numcharstoskip = 11
        statustext = statustext[ind1+numcharstoskip:]
        ind2 = statustext.find('"')
        status = statustext[:ind2]
        #Mapping GATE-03 states to supported values in HASS component
        if self._version == "GATE-03":
            status = GATE03_STATES_MAPPING.get(status.upper(), "UNKNOWN")
        _LOGGER.info("Egardia alarm status: "+status)
        return status.upper()

    def getsensors(self):
        """Get the sensors and their states from the alarm panel"""
        import requests
        try:
            if self._version in ["WV-1716", "GATE-01"]:
                sensors = self.dorequestwithretry('get', 'sensorListGet')
            elif self._version in ["GATE-02", "GATE-03"]:
                sensors = self.dorequestwithretry('get', 'deviceListGet')
            else:
                raise VersionError('Egardia device version '+self._version+' is unsupported.')
        except:
            raise
       
        if self.statusunauthorized(sensors):
            raise UnauthorizedError('Unable to login to system using the credentials provided')
        elif 'is not defined' in sensors:
            raise VersionError('Unable to communicate with the device. Did you configure your version correctly?')
        else:
            sensord = self.parseJson(sensors)
            sensors = {}
            keyname = "no"
            typename = "type"
            if self._version in ["GATE-02", "GATE-03"]:
                keyname = "id"
            if self._version == "GATE-03":
                typename = "type_f"
            if self._version in ["WV-1716", "GATE-02", "GATE-01", "GATE-04"]:
                #Process GATE-01 and GATE-02 sensor json
                for sensor in sensord["senrows"]:
                    if sensor[typename] not in SENSOR_TYPES_TO_IGNORE:
                        #Change keyname from no to id to match GATE-02 and GATE-03
                        if self._version in ["WV-1716", "GATE-01"]:
                            newkeyname = "id"
                            sensor[newkeyname] = sensor.pop(keyname)
                            sensors[sensor[newkeyname]] = sensor
                        elif self._version in ["GATE-02", "GATE-04"]:
                            sensors[sensor[keyname]] = sensor
                        #sensor[keyname]
                        #if sensor["type"] == "Door Contact":
                            #sensor["cond"]== "Open" || ""
                        #    k = 1
                        #if sensor["type"] == "IR Sensor":
                            #sensor[""]!= "" || ""
                        #    k = 2
            elif self._version == "GATE-03":
                #Process GATE-03 sensor json
                for sensor in sensord["senrows"]:
                    if sensor[typename] not in SENSOR_TYPES_TO_IGNORE:
                        #Change type_f key to type for GATE-03.
                        sensor["type"] = sensor.pop(typename)
                        sensors[sensor[keyname]]=sensor
            return sensors
        
    def getsensor(self, sensorId):
        self._sensors = self.getsensors()
        if sensorId in self._sensors:
            return self._sensors[sensorId]
        else:
            return None

    def getsensorstate(self, sensorId):
        sensor = self.getsensor(sensorId)
        if sensor is not None:
            if self._version in ["WV-1716", "GATE-01", "GATE-02"]:
                if len(sensor['cond']) > 0:
                    # Return True when door is open or IR is triggered
                    return True
                else:
                    # Return False when door is closed or IR is not triggered
                    return False
            elif self._version in ["GATE-03", "GATE-04"]:
                if sensor['status'].upper() in ["DOOR OPEN", "LÅS OP"]:
                    # Return True when door is open
                    return True
                elif sensor['status'].upper()  in ["DOOR CLOSE", "LÅS"]:
                    return False
        else:
            return None

    def getlockstate(self, door_id):
        sensor = self.getsensor(door_id)
        # Locks confusingly uses the same strings to indicate state as door sensors
        if sensor['status'].upper() == "DOOR CLOSE":
            return "locked"
        elif sensor['status'].upper() == "DOOR OPEN":
            return "unlocked"
        else:
            return "unknown"

    def getlocks(self):
        locks = {}
        sensors = self.getsensors()
        # type doesn't seem to be reliable, so we use the name instead
        for sensor_id, sensor in sensors.items():
            if "Door Lock" in sensor['type']:
                locks[sensor_id] = sensor
        return locks

    def set_lock_state(self, door_id, state):
        """Lock or unlock the door"""
        sensor = self.getsensor(door_id)
        if state.lower() == "lock":
            payload = {'id': door_id, 'switch': '1'}
        elif state.lower() == "unlock":
            payload = {'id': door_id, 'switch': '0'}
        else:
            raise ValueError("Invalid state. Use 'lock' or 'unlock'.")
        try:
            response = self.dorequestwithretry('POST', 'deviceSwitchPSSPost', 1, payload)
            if "result : 1" in response:
                return True
            else:
                return False
        except:
            raise


    def dorequest(self, requesttype, action, payload=None):
        """Execute an request against the alarm panel"""
        import requests
        requesttype = requesttype.upper()
        _LOGGER.info("Egardia doRequest, type: "+requesttype+", url: "+self.buildurl()+action
                     +", payload: "+str(payload)+", auth=("+self._username+",****)")
        if requesttype == 'GET':
            return requests.get(self.buildurl()+action,
                                auth=(self._username, self._password), timeout=5)
        elif requesttype == 'POST':
            return requests.post(self.buildurl()+action, data=payload,
                                 auth=(self._username, self._password), timeout=5)
        else:
            return None

    def buildurl(self):
        """Build the url from host and port"""
        return 'http://'+self._host+':'+str(self._port)+'/action/'

    def alarm_disarm(self, code=None):
        """Send disarm command."""
        if self._version in ["GATE-01", "GATE-02"]:
            req = self.sendcondition(4)
        elif self._version in ["GATE-03", "GATE-04"]:
            req = self.sendcondition(0)
        elif self._version == "WV-1716":
            req = self.sendcondition(2)
        
        _LOGGER.info("Egardia alarm disarming, result: "+req)

    def alarm_arm_home(self, code=None):
        """Send arm home command."""
        if self._version in ["WV-1716", "GATE-01", "GATE-02"]:
            req = self.sendcondition(1)
        elif self._version in ["GATE-03", "GATE-04"]:
            req = self.sendcondition(2)
        _LOGGER.info("Egardia alarm arming home, result: "+req)

    def alarm_arm_away(self, code=None):
        """Send arm away command."""
        #ARM the alarm
        if self._version in ["WV-1716", "GATE-01", "GATE-02"]:
            req = self.sendcondition(0)
        elif self._version in ["GATE-03", "GATE-04"]:
            req = self.sendcondition(1)
        _LOGGER.info("Egardia alarm arming away, result: "+req)

    def sendcondition(self, mode):
        "Change the condition of the panel"""
        import requests
        #Send payload to panelCondPost
        payload = {'area': '1', 'mode': mode}
        try:
            statustext = self.dorequestwithretry('POST', 'panelCondPost', 1, payload)
        except:
            raise
        ind1 = statustext.find('result : ')
        statustext = statustext[ind1+9:]
        ind2 = statustext.find(',')
        statustext = statustext[:ind2]
        return statustext

    def parseJson(self, crappy_json):
        import json
        import re
        crappy_json = crappy_json.replace("/*-secure-","")
        crappy_json = crappy_json.replace("*/","")
        crappy_json = crappy_json.replace('{	senrows : [','{"senrows":[')
        property_names_to_fix = ["no","type","type_f","area", "zone", "name", "attr", "cond", "cond_ok", "battery", "battery_ok", "tamp", "tamper", "tamper_ok", "bypass", "rssi", "status", "id","su"]
        for p in property_names_to_fix:
            crappy_json = crappy_json.replace(p+' :','"'+p+'":')
        data = json.loads(crappy_json, strict=False)
        return data
