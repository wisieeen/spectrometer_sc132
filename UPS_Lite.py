#!/usr/bin/env python3
"""Raspberry Pi UPS Hat monitor (CW2015) publishing battery metrics over MQTT.

Reads voltage and remaining capacity from the CW2015 via SMBus, publishes to MQTT topics,
and periodically prints the readings.
"""
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
        """Read battery voltage from CW2015 via SMBus.

        Inputs:
            bus: An initialized `smbus.SMBus` instance.
        Output:
            Battery voltage as a float in Volts.
        Transformation:
            Reads register `VCELL`, swaps endianness, and applies the CW2015 scaling factor (0.305/1000).
        """
        read = bus.read_word_data(CW2015_ADDRESS, CW2015_REG_VCELL)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        voltage = swapped * 0.305 /1000
        return voltage


def readCapacity(bus):
        """Read remaining battery capacity from CW2015 via SMBus.

        Inputs:
            bus: An initialized `smbus.SMBus` instance.
        Output:
            Remaining battery capacity as a float (percentage units as returned by the device model).
        Transformation:
            Reads register `SOC`, swaps endianness, and converts raw value by dividing by 256.
        """
        read = bus.read_word_data(CW2015_ADDRESS, CW2015_REG_SOC)
        swapped = struct.unpack("<H", struct.pack(">H", read))[0]
        capacity = swapped/256
        return capacity


def QuickStart(bus):
        """Wake the CW2015 and trigger a quick-start calculation.

        Inputs:
            bus: An initialized `smbus.SMBus` instance.
        Output:
            None (side-effect writes to the CW2015 `MODE` register).
        Transformation:
            Writes mode value `0x30` to the CW2015 quick-start register.
        """
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