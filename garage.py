from machine import Pin, reset, Timer
from time import sleep, ticks_ms, sleep_ms, localtime, time
from umqtt.simple import MQTTClient
import network
import ustruct
import dht
import ntptime
import micropython
import sys

#allocate emergency byffer to store trace if we die in interrupt handler
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

# log files
time_log = open("time.log","a")
def sync_time(t):
    try:
        print("Syncing clock...", end='')
        t=time()
        ntptime.settime()
        print("{}: {} s correction".format(t,time()-t), file=time_log)
        print('Done')
    except Exception as e:
        print('Error:',e)
        sys.print_exception(e, time_log)
        pass

# set up a timer to call sync_time every hour
ntp_timer = Timer(-1)
ntp_timer.init(period=1000*3600, mode=Timer.PERIODIC, callback=sync_time)

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

    try:
        # connect to the WLAN
        do_connect()

        # connect to the MQTT server
        c = MQTTClient("garage","192.168.1.8")
        c.set_callback(mqtt_callback)
        c.connect()
        c.subscribe(TOPIC_LEFT_DOOR_CMD)
        c.subscribe(TOPIC_RIGHT_DOOR_CMD)

        sync_time(1) # sync the clock wiht ntp

        # setup a periodic timer to sync time with NTP try every 4 hrs
        #ntp_timer = Timer(-1)
        #ntp_timer.init(period=1000*3600*4, mode=Timer.PERIODIC, callback=sync_time)

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

    except KeyboardInterrupt:
        print("Cntrl-C pressed!")
    except Exception as e:
        print("I died!")
        # log the error in a file so it's there later
        filename="crash_{}-{:02d}-{:02d}-{:02d}:{:02d}:{:02d}Z".format(*localtime())
        print(filename)
        with open(filename,"w") as ed:
            sys.print_exception(e, ed)
    finally:
        # stop the timer
        print("Stopping clock sync interrupt...")
        ntp_timer.deinit()

        #close the logs
        print("closing timelog...")
        time_log.close()

        # reboot
        #reset()
