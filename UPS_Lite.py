#!/usr/bin/env python3
import struct
import smbus
import sys
import time
import RPi.GPIO as GPIO

CW2015_ADDRESS   = 0X62
CW2015_REG_VCELL = 0X02
CW2015_REG_SOC   = 0X04
CW2015_REG_MODE  = 0X0A

import paho.mqtt.client as mqtt
import os

BROKER = "10.0.0.4"
PORT = 1883
USER = "lab"
PASS = "labpass"

TOPIC_CAPACITY = "lab/monocamera/batteryCapacity"
TOPIC_VOLTAGE = "lab/monocamera/batteryVoltage"
TOPIC_STATUS = "lab/monocamera/batteryStatus"

INTERVAL_SEC = 30

def readVoltage(bus):
        "This function returns as float the voltage from the Raspi UPS Hat via the provided SMBus object"
        read = bus.read_word_data(CW2015_ADDRESS, CW2015_REG_VCELL)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        voltage = swapped * 0.305 /1000
        return voltage


def readCapacity(bus):
        "This function returns as a float the remaining capacity of the battery connected to the Raspi UPS Hat via the provided SMBus object"
        read = bus.read_word_data(CW2015_ADDRESS, CW2015_REG_SOC)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        capacity = swapped/256
        return capacity


def QuickStart(bus):
        "This function wake up the CW2015 and make a quick-start fuel-gauge calculations "
        bus.write_word_data(CW2015_ADDRESS, CW2015_REG_MODE, 0x30)
      



       
#----------------------------------------------------------------------------------
        
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(4,GPIO.IN)  # GPIO4 is used to detect whether an external power supply is inserted
  
bus = smbus.SMBus(1)  # 0 = /dev/i2c-0 (port I2C0), 1 = /dev/i2c-1 (port I2C1)


QuickStart(bus)

client = mqtt.Client()
client.username_pw_set(USER, PASS)
client.connect(BROKER, PORT, 60)
client.loop_start()

try:
    while True:
        try:
            voltage = readVoltage(bus)
            capacity = readCapacity(bus)

            client.publish(TOPIC_VOLTAGE, "{:.2f}".format(voltage), qos=0, retain=False)
            client.publish(TOPIC_CAPACITY, str(int(round(capacity))), qos=0, retain=False)

            print("Voltage: {:.2f} V  Capacity: {}% ".format(voltage, int(round(capacity))))
            
        except OSError as e:
            print("I2C read error:", e)

        time.sleep(INTERVAL_SEC)
except KeyboardInterrupt:
    client.loop_stop()
    client.disconnect()
    print("Stopped.")