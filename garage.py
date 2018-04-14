from machine import Pin, reset, Timer
from time import sleep, ticks_ms, sleep_ms, localtime, time
from umqtt.robust import MQTTClient
import network
import ustruct
import dht
import ntptime
import micropython
import sys
import credentials

#allocate emergency buffer to store trace if we die in interrupt handler
micropython.alloc_emergency_exception_buf(100)

# define the pins
pin_led = Pin(2, Pin.OUT)
pin_left_contact = Pin(12, Pin.IN, Pin.PULL_UP)
pin_right_contact = Pin(14, Pin.IN, Pin.PULL_UP)
pin_left_relay = Pin(4, Pin.OUT)
pin_right_relay = Pin(5, Pin.OUT)
th_sens = dht.DHT22(Pin(13))
pin_left_relay.value(1)
pin_right_relay.value(1)
pin_led.value(1)

# define some globals
prev_left_contact = -1
prev_right_contact = -1
last_check = 0

# define topics
TOPIC_LEFT_DOOR_STATUS = b"garage/leftDoor"
TOPIC_RIGHT_DOOR_STATUS = b"garage/rightDoor"
TOPIC_LEFT_DOOR_CMD = b"garage/leftDoor/cmd"
TOPIC_RIGHT_DOOR_CMD = b"garage/rightDoor/cmd"
TOPIC_TEMPERATURE = b"garage/temperature"
TOPIC_HUMIDITY = b"garage/humidity"

ntptime.host = "router.stevesell.com"


def sync_time(t):
    try:
        #time_log = open("time.log","a")
        print("Syncing clock...", end='')
        t=time()
        ntptime.settime()
        #print("{}: {} s correction".format(t,time()-t), file=time_log)
        print("{}: {} s correction".format(t,time()-t))
        print('Done')
    except Exception as e:
        print('Error:',e)
        #sys.print_exception(e, time_log)
    finally:
        #time_log.close()
        pass

def do_connect():
    # Get wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # Disable the AP WebRepl
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    if not wlan.isconnected():
        print('connecting to network...')
        wlan.connect(credentials.SSID, credentials.PASS)
        while not wlan.isconnected():
            pass
    else:
        print("Already connected...")
    print('network config:', wlan.ifconfig())

def push(relay):
    relay.off()    # relay is active low
    sleep_ms(500)
    relay.on()

def mqtt_callback(topic, payload):
    global prev_left_contact, prev_right_contact

    print("Topic:",topic,"Payload:", payload)

    if topic == TOPIC_LEFT_DOOR_CMD:
        if (payload == b'open') and (prev_left_contact == 0):
            push(pin_left_relay)
        if (payload == b'close') and (prev_left_contact == 1):
            push(pin_left_relay)

    if topic == TOPIC_RIGHT_DOOR_CMD:
        if (payload == b'open') and (prev_right_contact == 0):
            push(pin_right_relay)
        if (payload == b'close') and (prev_right_contact == 1):
            push(pin_right_relay)

    if payload == b'refresh':
        print("Forcing refresh of door status")
        prev_left_contact = -1
        prev_right_contact = -1

def contact_check(t):
    global prev_left_contact, prev_right_contact

    left_contact = pin_left_contact.value()
    right_contact = pin_right_contact.value()

    if (prev_left_contact != left_contact):
        prev_left_contact = left_contact
        if left_contact == 0:
            c.publish(TOPIC_LEFT_DOOR_STATUS,b"closed", retain=True)
        elif left_contact == 1:
            c.publish(TOPIC_LEFT_DOOR_STATUS,b"open", retain=True)

    if (prev_right_contact != right_contact):
        prev_right_contact = right_contact
        if right_contact == 0:
            c.publish(TOPIC_RIGHT_DOOR_STATUS,b"closed", retain=True)
        elif right_contact == 1:
            c.publish(TOPIC_RIGHT_DOOR_STATUS,b"open", retain=True)

def check_dht22(t):
    try:
        print("Checking DHT22...", end='')
        th_sens.measure()
        temp =  th_sens.temperature()
        humid = th_sens.humidity()
        print("OK")
        temp_bytestring = "{:.1f}".format(temp*1.8+32.0)
        c.publish(TOPIC_TEMPERATURE,
                  ustruct.pack('{}s'.format(len(temp_bytestring)),temp_bytestring),
                               retain=True)
        prev_humid = humid
        c.publish(TOPIC_HUMIDITY,
                  ustruct.pack('{}s'.format(len(str(humid))),str(humid)),
                  retain=True)
    except:
        print("Error")


# sync the clock every 4 hours (ESP8266 needs to do this at least every 7h due
# to clock counter rollover)
ntp_timer = Timer(-1)
ntp_timer.init(period=1000*3600*4, mode=Timer.PERIODIC, callback=sync_time)

# get temp and humidity every 5 min
dht22_timer = Timer(-1)
dht22_timer.init(period=1000*300, mode=Timer.PERIODIC, callback=check_dht22)

# check the door status every 100 ms
door_check = Timer(-1)
door_check.init(period=100, mode=Timer.PERIODIC, callback=contact_check)

do_connect()

# connect to the MQTT server
c = MQTTClient("garage","192.168.1.8")
c.DEBUG=True
c.set_callback(mqtt_callback)
if not c.connect(clean_session=False):
    print("New session being set up")
    c.subscribe(TOPIC_LEFT_DOOR_CMD)
    c.subscribe(TOPIC_RIGHT_DOOR_CMD)

sync_time(1) # sync the clock wiht ntp


def main():


    try:
        # main loop
        print("Entering main loop.  Waiting for something to happen.")
        while True:
            # Check for incoming MQTT messages
            c.wait_msg()

    except KeyboardInterrupt:
        print("Cntrl-C pressed!")
    except Exception as e:
        print("I died!")
        # log the error in a file so it's there later
        filename="crash_{}-{:02d}-{:02d}-{:02d}{:02d}{:02d}Z".format(*localtime())
        print(filename)
        with open(filename,"w") as ed:
            sys.print_exception(e, ed)
    finally:
        # stop the timer
        print("Stopping clock sync interrupt...")
        ntp_timer.deinit()
        dht22_timer.deinit()
