from machine import Pin, reset
from time import sleep, ticks_ms, sleep_ms
from umqtt.simple import MQTTClient
import network
import ustruct
import dht

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

def do_connect():
    # Get wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # Disable the AP WebRepl
    ap = network.WLAN(network.AP_IF)
    ap.active(False)
    if not wlan.isconnected():
        print('connecting to network...')
        wlan.connect('Magnum', 'supersecretpassword')
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

def main():
    # globals
    global prev_left_contact, prev_right_contact, last_check

    # connect to the WLAN
    do_connect()

    # connect to the MQTT server
    c = MQTTClient("garage","192.168.1.8")
    c.set_callback(mqtt_callback)
    c.connect()
    c.subscribe(TOPIC_LEFT_DOOR_CMD)
    c.subscribe(TOPIC_RIGHT_DOOR_CMD)

    # main loop
    while True:
        # Check the state of the doors
        left_contact = pin_left_contact.value()
        right_contact = pin_right_contact.value()

        # Update them if necessary
        if (prev_left_contact != left_contact):
            print("Left door status changed to:", left_contact)
            prev_left_contact = left_contact
            if left_contact == 0:
                c.publish(TOPIC_LEFT_DOOR_STATUS,b"closed")
            elif left_contact == 1:
                c.publish(TOPIC_LEFT_DOOR_STATUS,b"open")

        if (prev_right_contact != right_contact):
            print("Right door status changed to:", right_contact)
            prev_right_contact = right_contact
            if right_contact == 0:
                c.publish(TOPIC_RIGHT_DOOR_STATUS,b"closed")
            elif right_contact == 1:
                c.publish(TOPIC_RIGHT_DOOR_STATUS,b"open")

        # update the temperature and humidity if it's different than last time
        # and it has been longer than 5s
        now = ticks_ms()
        if now-last_check > 60000:
            print("Checking DHT22...",end='')
            last_check = now
            try:
                th_sens.measure()
                temp =  th_sens.temperature()
                humid = th_sens.humidity()
                print("OK")
                temp_bytestring = "{:.1f}".format(temp*1.8+32.0)
                c.publish(TOPIC_TEMPERATURE,
                          ustruct.pack('{}s'.format(len(temp_bytestring)),temp_bytestring))
                prev_humid = humid
                c.publish(TOPIC_HUMIDITY,
                          ustruct.pack('{}s'.format(len(str(humid))),str(humid)))
            except:
                print("Error")

        # Check for incoming MQTT messages
        c.check_msg()

        # take a break
        sleep_ms(100)

try:
    main()
except OSError:
    machine.reset()
except IndexError:
    machine.reset()
