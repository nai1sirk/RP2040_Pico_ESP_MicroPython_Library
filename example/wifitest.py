import utime
import WiFi

# enter your network
SSID = "<<YOUR SSID>>"
PWD = "<<YOUR PASSWORD>>"

SERVER = "www.example.com"
PORT = 443
URL = "/"

print(f'[WiFi] Init (should be True): {WiFi.init(0)}')
print(f'[WiFi] Status (should be 4): {WiFi.status()}')
print(f'[WiFi] Begin (should be 1): {WiFi.begin(SSID, PWD, None)}')
if (WiFi.status() == WiFi.WL_CONNECTED):
    print("[WiFi] Connected to the network")
    print(f'[WiFi] Status (should be {WiFi.WL_CONNECTED}): {WiFi.status()}')
    print(f'[WiFi] Channel = {WiFi.channel()}, RSSI = {WiFi.rssi()}')
    print(f'[WiFi] IP = {WiFi.localIp()}, gateway = {WiFi.gatewayIp()}, subnet = {WiFi.subnetMask()}')
    print(f'[WiFi] DNS servers: {WiFi.dnsIp(1)}, {WiFi.dnsIp(2)}')

cli = WiFi.Client()
if (cli.connectSSL(SERVER, PORT)):
    print("[WiFiClient] Connected to server");
   
    c = cli.connected()
    print(f'[WiFiClient] Connected (should be True): {c}')

    cli.print(f'GET {URL} HTTP/1.1\r\nHost: {SERVER}\r\n\r\n')
    t = utime.ticks_ms()
    while (cli.available() == 0 and utime.ticks_ms() - t < 5000):  # timeout 5 s
        utime.sleep(0.01)
    
    p = cli.peek();
    print(f'[WifiClient] First char (should be H): {chr(p)}')
    
    resp = bytearray()
    while (cli.available()):
        ch = cli.read()

        if (ch < 0):
            break;  # error condition

        resp.append(ch)
        
        t = utime.ticks_ms()
        while (cli.available() == 0 and utime.ticks_ms() - t < 1000):  # timeout 1 s
            utime.sleep(0.01)
            
    f = resp.find(b'\r\n\r\n')
    if (f > 0):
        hdr = resp[:f].decode().split('\r\n')
        body = resp[f+4:]
        print(f'Header ({len(hdr)} lines):')
        print(hdr)
        print(f'Body ({len(body)} bytes):')
        print(body)
    else:
        print('Response:')
        print(resp)

cli.stop()

c = cli.connected()
print(f'[WiFiClient] Connected (should be False): {c}')

if (WiFi.disconnect(False)):
    print("[WiFi] Disconnected")
