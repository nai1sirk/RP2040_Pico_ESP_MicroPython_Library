# EspAtDrv.py
#
# Driver for ESP8255 on Chinese RPi Pico W
#
# Communication with ESP8255 over UART0 at 115200 Bd
#
# Based on source: https://github.com/jandrassy/WiFiEspAT
#
# Version:
#  0.1.0: initial version

from machine import UART
from micropython import const
import utime

class EspAtDrv_linkInfo:
    def __init__(self):
        self.flags = 0
        self.avail = 0

###################################

# constants
# Logging: setting to True enables the particular logging
LOG_ERROR = const(True)
LOG_INFO = const(False)
LOG_DEBUG = const(False)

LINKS_COUNT = const(5)

NO_LINK = const(255)

Error_NO_ERROR = const(0)
Error_NOT_INITIALIZED = const(1)
Error_AT_NOT_RESPONDING = const(2)
Error_AT_ERROR = const(3)
Error_NO_AP = const(4)
Error_LINK_ALREADY_CONNECTED = const(5)
Error_LINK_NOT_ACTIVE = const(6)
Error_RECEIVE = const(7)
Error_SEND = const(8)
Error_UDP_BUSY = const(9)
Error_UDP_LARGE = const(10)
Error_UDP_TIMEOUT = const(11)

WIFI_SOFT_RESET = const(0)
#WIFI_HARD_RESET = 1
WIFI_EXTERNAL_RESET = const(2)

WIFI_MODE_STA = const(1)  # 0b01
WIFI_MODE_SAP = const(2)  # 0b10

TIMEOUT = const(1000)
TIMEOUT_COUNT = const(5)

LINK_CONNECTED = const(1)         # (1 << 0)
LINK_CLOSING = const(2)           # (1 << 1)
LINK_IS_INCOMING = const(4)       # (1 << 2)
LINK_IS_ACCEPTED = const(8)       # (1 << 3)
LINK_IS_UDP_LISTENER = const(16)  # (1 << 4)

# static variables
linkInfo = None
lastErrorCode = Error_NO_ERROR
espUART = None
buffer = bytearray()
wifiMode = 0
wifiModeDef = 0
persistent = False
lastSync = 0  # in milliseconds
 
def init(resetType: int) -> int:
    global espUART, lastErrorCode, linkInfo
    
    # Configure UART for communication with ESP8285
    espUART = UART(0, 115200, timeout=1000, timeout_char=100)

    lastErrorCode = Error_NO_ERROR
    
    linkInfo = []
    for i in range(LINKS_COUNT):
        linkInfo.append(EspAtDrv_linkInfo())
        
    return reset(resetType)

def reset(resetType: int) -> int:
    global wifiMode, wifiModeDef, buffer
    
    if (resetType != WIFI_EXTERNAL_RESET):
        maintain()
        
    if (resetType == WIFI_SOFT_RESET):
        LOG_INFO_PRINT("soft reset\r\n")

        sendString("AT+RST")
        sendCommand("ready", True, False)  # can be missed
    else:
        LOG_INFO_PRINT("no reset\r\n")

    if (not simpleCommand("ATE0") or             # turn off echo. must work
        not simpleCommand("AT+CIPMUX=1") or      # Enable multiple connections.
        not simpleCommand("AT+CIPRECVMODE=1")):  # Set TCP Receive Mode - passive
        return False

    # read default wifi mode
    sendString("AT+CWMODE?")
    if (not sendCommand("+CWMODE", True, False)):
        return False

    wifiMode = buffer[8] - ord('0')  # '+CWMODE:'
    if (not readOK()):
        return False

    wifiModeDef = wifiMode
    return True

def maintain():
    global lastErrorCode
    
    lastErrorCode = Error_NO_ERROR
    return readRX(None, False, False)

def sendString(cmd: str) -> int:
    global espUART
    
    LOG_DEBUG_PRINT(cmd, False)
    n = espUART.write(cmd)
    return (n == len(cmd))
    
def sendCommand(expected: str, bufferData: int, listItem: int):
    global lastErrorCode
    
    # AT command is already printed, but not 'entered' with "\r\n"
    LOG_DEBUG_PRINT(" ...sent", False)

    # finish AT command sending
    if (sendString("\r\n") != True):
        lastErrorCode = Error_AT_NOT_RESPONDING  # UART error
        return False

    if (expected):
        return readRX(expected, bufferData, listItem)
    else:
        return readOK()

def simpleCommand(cmd: str) -> int:
    maintain()
    if (not sendString(cmd)):
        return False

    LOG_DEBUG_PRINT(" ...sent", False)
    if (not sendString("\r\n")):
        return False

    return readOK()

def readRX(expected: str, bufferData: int, listItem: int) -> int:
    global espUART, buffer, lastErrorCode, linkInfo
    
    timeout = 0
    unlinkBug = False
    ignoredCount = 0

    while True:
        avail = espUART.any()
        if (not expected and avail == 0):
            return True

        buffer = bytearray()

        b = espUART.read(1)
        if (b == None):  # read first byte with stream's timeout
            # timeout or unconnected
            if (timeout == TIMEOUT_COUNT):
                LOG_ERROR_PRINT("AT firmware not responding\r\n")
                lastErrorCode = Error_AT_NOT_RESPONDING
                return False

            # next we send an invalid command to AT.
            sendString("?")
            # response is:
            # nothing if the firmware doesn't respond at all. readBytes will timeout again
            # "busy p..." if still processing a command. will be printed to debug output and ignored
            # ERROR if we missed some unexpected response of a current command. will be evaluated as ERROR
            timeout += 1
            continue

        buffer.extend(b)
    
        pos = 1  # last position in the buffer

        if (buffer[0] == ord('>')):
            # AT+CIPSEND prompt
            # AT versions 1.x send a space after '>', we must clear it
            espUART.read(1)
            timeout = 0  # AT firmware responded
            
        else:
            b = espUART.read(1)  # read second byte with stream's timeout
            if (b == None):  
                continue  # No processing when the firmware not responded
            timeout = 0  # AT firmware responded
            buffer.extend(b)

            pos += 1
            if (buffer.startswith(b'\r\n')):  # empty line. skip it
                continue
            terminator = b'\n'
            
            if (buffer[0] == ord('+')):
                # +IPD, +CIP
                if (buffer[1] == ord('C') and not bufferData):
                    # +CIP
                    terminator = b':'
                elif (buffer[1] == ord('I')):
                    # +IPD
                    buffer.extend(espUART.read(4))  # // (+I)PD,i
# FIXME:
#                        int8_t linkId = buffer[SL_IPD] - '0';
#                        if (linkInfo[linkId].isUdpListener())
#                        {
#                            terminator = ':';
#                        }
            while (True):
                b = espUART.read(1)
                if (b == None or b == terminator):
                    break
                buffer.extend(b)
                pos += 1
                # TODO: Check the buffer size
                
            while (buffer[-1] == 13):
                # 'while' because some (ignored) messages have \r\r\n
                pos -= 1  # trim \r
                buffer = buffer[:-1]

        LOG_DEBUG_PRINT(buffer)

        if (expected and buffer.startswith(expected)):
            LOG_DEBUG_PRINT(" ...matched\r\n", False)
            return True
        
        if (buffer.startswith("+IPD,")):
            linkId = buffer[5] - ord('0')
            recLen = int(buffer[7:])

            if (linkId >= 0 and linkId < LINKS_COUNT and recLen > 0):  # TODO check if he link is opened
                linkInfo[linkId].avail = recLen
                LOG_DEBUG_PRINT(" ...processed\r\n")
            else:
                # +IPD truncated in serial buffer overflow
                LOG_DEBUG_PRINT(" ...ignored\r\n")

        elif (buffer[1:].startswith(",CONNECT")):
            linkId = buffer[0] - ord('0')

            if (linkInfo[linkId].avail == 0
                    and (not (linkInfo[linkId].flags & LINK_CONNECTED)
                            or (linkInfo[linkId].flags & LINK_CLOSING))):
                # incoming connection (and we could miss CLOSED)
                linkInfo[linkId].flags = LINK_CONNECTED | LINK_IS_INCOMING
                LOG_DEBUG_PRINT(" ...processed\r\n", False)
            else:
                LOG_DEBUG_PRINT(" ...ignored\r\n", False)
                
        elif (buffer[1:].startswith(",CLOSED") or
              buffer[1:].startswith(",CONNECT FAIL")):
            linkId = buffer[0] - ord('0')
            linkInfo[linkId].flags = 0
            LOG_DEBUG_PRINT(" ...processed\r\n", False)
            LOG_INFO_PRINT(f'closed linkId {linkId}\r\n')

        elif (buffer.startswith("ERROR") or buffer == b'FAIL'):
            if (unlinkBug):
                LOG_DEBUG_PRINT(" ...UNLINK is OK\r\n", False)
                return True
            if (expected == None or expected == ""):
                LOG_DEBUG_PRINT(" ...ignored\r\n", False)  # it is only a late response to timeout query '?'
            else:
                LOG_DEBUG_PRINT(" ...error\r\n", False)
                LOG_ERROR_PRINT(f'expected {expected} got {buffer.decode()}\r\n')
                lastErrorCode = Error_AT_ERROR
                return False
            
        elif (buffer == b'No AP'):
            LOG_DEBUG_PRINT(" ...processed\r\n", False)
            LOG_ERROR_PRINT(f'expected {expected} got {buffer.decode()}\r\n')
            lastErrorCode = Error_NO_AP
            return False

        elif (buffer == b'UNLINK'):
            unlinkBug = True
            LOG_DEBUG_PRINT(" ...processed\r\n", False)
            
        elif (listItem and buffer == b'OK'):
            # OK ends the listing of unknown items count
            LOG_DEBUG_PRINT(" ...end of list\r\n", False)
            return False
        
        else:
            ignoredCount += 1
            if (ignoredCount > 70):
                # reset() has many ignored lines
                LOG_ERROR_PRINT("Too much garbage on RX\r\n")
                lastErrorCode = Error_AT_NOT_RESPONDING
                return False
            LOG_DEBUG_PRINT(" ...ignored\r\n", False)
            
    return False

def readOK() -> int:
    return readRX("OK", True, False)

def staStatus() -> int:
    global wifiModedef, lastErrorCode, buffer
    
    maintain()

    LOG_INFO_PRINT("wifi status\r\n")

    if (wifiModeDef == 0):
        # reset() was not executed successfully
        LOG_ERROR_PRINT("AT firmware was not initialized\r\n")
        lastErrorCode = Error_NOT_INITIALIZED
        return -1

    if (sendString("AT+CIPSTATUS") != True):
        lastErrorCode = Error_AT_NOT_RESPONDING
        return -1

    if (sendCommand("STATUS", True, False) != True):
        return -1

    status = buffer[7] - ord('0')  # 'STATUS:'
    return status if readOK() else -1

def joinAP(ssid: str, password: str, bssid: bytearray):
    global wifiMode, persistent
    
    maintain()

    LOG_INFO_PRINT(f'join AP {ssid}')
    LOG_INFO_PRINT(" persistent\r\n" if persistent else " current\r\n", False)

    if (setWifiMode(wifiMode | WIFI_MODE_STA, persistent) == False):
        return False  # can't join ap without sta mode

    if (persistent):
        sendString("AT+CWJAP=\"")
    else:
        sendString("AT+CWJAP_CUR=\"")
    sendString(ssid)

    if (password):
        sendString("\",\"")
        sendString(password)

        if (bssid):
            sendString("\",\"")
            hx = ''
            for i in range(6):
                hx += ":%02X" % bssid[i]
            sendString(hx[1:])

    sendString("\"")
    if (sendCommand(None, True, False) == False):
        return False

    if (persistent):
        simpleCommand("AT+CWAUTOCONN=1")

    return True

def setWifiMode(mode: int, save: int) -> int:
    global wifiMode, wifiModeDef, lastErrorCode
    
    if (wifiModeDef == 0):
        # reset() was not executed successful
        LOG_ERROR_PRINT("AT firmware was not initialized\r\n")
        lastErrorCode = Error_NOT_INITIALIZED
        return False

    if (mode == 0):
        mode = WIFI_MODE_STA

    if (mode == wifiMode and (not save or mode == wifiModeDef)):  # no change
        return True

    sendString("AT+CWMODE=" if save else "AT+CWMODE_CUR=")
    sMode = chr(mode + ord('0'))
    sendString(sMode)
    if (sendCommand(None, True, False) == False):
        return False

        wifiMode = mode
        if (save):
            wifiModeDef = mode

        return True

def connect(type: str, host: str, port: int) -> int:
    global linkInfo, lastErrorCode
    
    maintain()

    linkId = freeLinkId()
    if (linkId == NO_LINK):
        return NO_LINK

    LOG_INFO_PRINT(f'start {type} to {host}:{port} on link {linkId}\r\n')

    link = linkInfo[linkId]

    if (link.flags & LINK_CONNECTED):
        LOG_ERROR_PRINTF(f'linkId {linkId} is already connected.\r\n')
        lastErrorCode = Error_LINK_ALREADY_CONNECTED
        return NO_LINK

    cmd = f'AT+CIPSTART={linkId},"{type}","{host}",{port}'
    if (sendString(cmd) != True):
        link.flags = 0
        return NO_LINK

#if 0  // TODO:
#	if (udpLocalPort != 0)
#	{
#		cmd->print(',');
#		cmd->print(udpLocalPort);
#		cmd->print(",2");
#	}
#endif

    if (sendCommand(None, True, False) == False):
        link.flags = 0
        return NO_LINK

    link.flags = LINK_CONNECTED

#if 0  // TODO:
#	if (udpLocalPort != 0)
#	{
#		link.flags |= LINK_IS_UDP_LISTNER;
#		link.udpDataCallback = udpDataCallback;
#	}
#endif
    return linkId

def freeLinkId():
    global linkInfo
    
    maintain()

    for linkId in range(LINKS_COUNT-1, -1, -1):
        link = linkInfo[linkId]

        if ((link.flags & (LINK_CONNECTED | LINK_CLOSING)) == 0 and link.avail == 0):
            LOG_INFO_PRINT(f'free linkId is {linkId}\r\n')
            return linkId

    return NO_LINK

def quitAP(save: int) -> int:
    global wifiMode, persistent
    
    LOG_INFO_PRINT("quit AP ")
    LOG_INFO_PRINT(" persistent\r\n" if (persistent or save) else " current\r\n", False)

    if (wifiMode == WIFI_MODE_SAP):
        # STA is off
        LOG_WARN_PRINT("STA is off\r\n")
        return False

    if (persistent or save):
        if (simpleCommand("AT+CWAUTOCONN=0") == False):  # don't reconnect on reset
            return False
        if (simpleCommand("AT+CIPDNS_DEF=0") == False):  # clear static DNS servers
            return False
        if (simpleCommand("AT+CWDHCP=1,1") == False):  # enable DHCP back in case static IP disabled it
            return False
    else:
        if (simpleCommand("AT+CIPDNS_CUR=0") == False):  # clear static DNS servers
            return False
        if (simpleCommand("AT+CWDHCP_CUR=1,1") == False):  # enable DHCP back in case static IP disabled it
            return False

    return simpleCommand("AT+CWQAP")  # it doesn't clear the persistent settings

def close(linkId: int, abort: int) -> int:
    global linkInfo
    
    maintain()

    LOG_INFO_PRINT(f'close link {linkId}\r\n')

    link = linkInfo[linkId]
    link.avail = 0

    if (not (link.flags & LINK_CONNECTED)):
        LOG_INFO_PRINT("link is already closed\r\n")
        return True

    link.flags |= LINK_CLOSING

    if (abort):
        if (sendString(f'AT+CIPCLOSEMODE={linkId},1') != True):
            return False
        sendCommand(None, True, False)  # Note: do not check the return value

    if (sendString(f'AT+CIPCLOSE={linkId}') != True):
        return False
    
    return sendCommand(None, True, False)

def sendData(linkId: int, buff: bytes) -> int:
    global linkInfo, espUART, buffer, lastErrorCode
    
    maintain()

    LOG_INFO_PRINT(f'send data on link {linkId}\r\n')

    if (len(buff) == 0):
        return 0
    
    if (not (linkInfo[linkId].flags & LINK_CONNECTED)):
        LOG_ERROR_PRINT("link is not connected\r\n")
        lastErrorCode = Error_LINK_NOT_ACTIVE
        return 0

    sendString(f'AT+CIPSEND={linkId},{len(buff)}')

#   // TODO
#	if (udpHost != nullptr)
#	{
#		cmd->print(F(",\""));
#		cmd->print(udpHost);
#		cmd->print(F("\","));
#		cmd->print(udpPort);
#	}

    if (sendCommand(">", True, False) == False):
        return 0

    if (espUART.write(buff) != len(buff)):
        return 0

    if (readRX("Recv ", True, False) == False):
        return 0

    l = buffer.find(b' ', 5)
    sendOk = False
    
    if (l > 0):
        rLen = int(buffer[5:l])

        if (readRX("SEND ", True, False) == True):  # SEND OK or SEND FAIL
            if (buffer[5:7] == b'OK'):
                sendOk = True

    if (not sendOk):
        LOG_ERROR_PRINT("failed to send data\r\n")
        lastErrorCode = Error_SEND
        return 0
    
    LOG_INFO_PRINT(f'\tsent {rLen} bytes on link {linkId}\r\n')
    return rLen

def availData(linkId: int) -> int:
    global linkInfo
    
    maintain()

    if (linkInfo[linkId].avail == 0 and
        (linkInfo[linkId].flags & (LINK_CONNECTED | LINK_CLOSING)) == LINK_CONNECTED):
        syncLinkInfo()

    return linkInfo[linkId].avail

def syncLinkInfo() -> int:
    global lastSync
    
    if (utime.ticks_ms() - lastSync < 500):
        return False
    lastSync = utime.ticks_ms()

    LOG_INFO_PRINT("sync\r\n")

    return checkLinks() and recvLenQuery()

def checkLinks() -> int:
    global buffer, linkInfo
    
    maintain()

    sendString("AT+CIPSTATUS")
    if (sendCommand("STATUS", True, False) == False):
        return False

    ok = [False] * LINKS_COUNT

    while (readRX("+CIPSTATUS", True, True)):
        linkId = buffer[11] - 48  # '+CIPSTATUS:'
        ok[linkId] = True

    for linkId in range(LINKS_COUNT):
        link = linkInfo[linkId]

        if (ok[linkId]):
            if (not (link.flags & (LINK_CONNECTED)) and (link.flags & (LINK_CLOSING))):
                # missed incoming connection
                link.flags = LINK_CONNECTED | LINK_IS_INCOMING
        else:
            # not connected
            flags = 0

    return True

def recvLenQuery() -> int:
    global buffer, linkInfo
    
    maintain()

    sendString("AT+CIPRECVLEN?")
    if (sendCommand("+CIPRECVLEN", True, False) == False):
        return False

    tok = buffer[12:].split(b',')  # '+CIPRECVLEN:'
    for linkId in range(LINKS_COUNT):
        if (linkId > len(tok)):
            break

        if (len(tok[linkId]) > 0):
            linkInfo[linkId].avail = int(tok[linkId])

    return readOK()

def recvData(linkId: int, buffSize: int = 1000) -> bytes:
    global linkInfo, lastErrorCode, buffer, espUART
    
    maintain()

    LOG_INFO_PRINT(f'get data on link {linkId}\r\n')

    if (linkInfo[linkId].avail == 0):
        if (not linkInfo[linkId].flags & LINK_CONNECTED):
            LOG_WARN_PRINT("link is not active\r\n")
            lastErrorCode = Error_LINK_NOT_ACTIVE
        else:
            LOG_WARN_PRINT("no data for link\r\n")
        return b''

    sendString(f'AT+CIPRECVDATA={linkId},{buffSize}')

    if (sendCommand("+CIPRECVDATA", False, False) == False):
        LOG_ERROR_PRINT(f'error receiving on link {linkId}\r\n')
        linkInfo[linkId].avail = 0
        lastErrorCode = Error_RECEIVE
        return 0

    explen = int(buffer[13:])  # "+CIPRECVDATA," AT 1.7.x has : after <data_len> (not matching the doc)
    b = espUART.read(explen)

    if (len(b) != explen):  # timeout
        LOG_ERROR_PRINT(f'error receiving on link {linkId}\r\n')
        linkInfo[linkId].avail = 0
        lastErrorCode = Error_RECEIVE
        return b''

    if (explen > linkInfo[linkId].avail):
        linkInfo[linkId].avail = 0
    else:
        linkInfo[linkId].avail -= explen

    readOK()

    LOG_INFO_PRINT(f'\tgot {explen} bytes on link {linkId}\r\n')

    return b

def getLastErrorCode() -> int:
    global lastErrorCode
    
    return lastErrorCode

def sysPersistent(_persistent: int) -> int:
    global persistent
    
    persistent = _persistent
    return True

def connected(linkId: int) -> int:
    global linkInfo
    
    maintain()
    link = linkInfo[linkId]
    return (link.flags & LINK_CONNECTED) and not (link.flags & LINK_CLOSING)

def apQuery() -> list:
    global wifiMode, buffer
    
    maintain()
    if (wifiMode != WIFI_MODE_STA):
        LOG_ERROR_PRINT("STA is off\r\n", True)
        return None;

    sendString("AT+CWJAP?")
    if (sendCommand("+CWJAP", True, False) == True):
        return buffer.split(b',')
    return None;

def staIpQuery() -> list:
    global buffer
    
    maintain()
    ret = []

    sendString("AT+CIPSTA?")
    if (sendCommand("+CIPSTA", True, False) == False):
        return None
    for i in  range(3):
        ret.append(buffer.split(b':')[2][1:-1].decode())
        if (i < 2):
            if (readRX("+CIPSTA", True, False) == False):
                return None
    readOK()
    
    return ret        

def dnsQuery() -> list:
    global buffer
    
    maintain()
    ret = []

    sendString("AT+CIPDNS_CUR?")
    if (sendCommand("+CIPDNS_CUR", True, False) == False):
        return None
    ret.append(buffer.split(b':')[1].decode())
    if (readRX("+CIPDNS_CUR", True, False) == False):
        return None
    ret.append(buffer.split(b':')[1].decode())
    readOK()
        
    return ret


####################### For Debugging 

def LOG_INFO_PRINT(x: str = None, prefix: int = True):
    if (LOG_INFO):
        if (x == None or prefix):
            print("[Wifi-i] ", end="")
        if (x != None):
            print(x, end="")
    
def LOG_ERROR_PRINT(x: str = None, prefix: int = True):
    if (LOG_ERROR):
        if (x == None or prefix):
            print("[Wifi-w] ", end="")
        if (x != None):
            print(x, end="")

def LOG_DEBUG_PRINT(x: str = None, prefix: int = True):
    if (LOG_DEBUG):
        if (x == None or prefix):
            print("[Wifi-d] ", end="")
        if (x != None):
            print(x, end="")
