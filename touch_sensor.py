import RPi.GPIO as GPIO
import time

# GPIO pin numbers
sensor1 = 17
sensor2 = 27

GPIO.setmode(GPIO.BCM)

GPIO.setup(sensor1, GPIO.IN)
GPIO.setup(sensor2, GPIO.IN)

print("Touch sensors ready")

try:
    while True:
        if GPIO.input(sensor1) == 1:
            print("Sensor 1 touched")

        if GPIO.input(sensor2) == 1:
            print("Sensor 2 touched")

        time.sleep(0.1)

except KeyboardInterrupt:
    GPIO.cleanup()
