"""
DPS Sensor Library for infineon optimus board

This library provides functions to interface with the Infineon DPS310 pressure sensor.

Author: Powen Ko
Email: powenkoads@gmail.com

Infineon Optimus Board can be purchased at www.ifroglab.com

Copyright (c) 2024 Powen Ko & infineon

GPT License v3:

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

"""



# pip install smbus2 qrcode requests pillow pyperclip
# pip install RPi.GPIO
# pip install smbus2 qrcode requests pyperclip

import smbus2
import time
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
import requests
import qrcode
from tkinter import Tk, Label, Text, Scrollbar, VERTICAL, Button, END, PhotoImage
import pyperclip
from threading import Thread
import io
from datetime import datetime
import RPi.GPIO as GPIO

from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageTk

# Define the I2C bus and the possible addresses of the DPS310
I2C_BUS = 1
DPS310_ADDRESSES = [0x77, 0x76]
PORT = 8080

# Define GPIO pins
PIN35 = 35   # distance 0
PIN36 = 36   # distance 1
PIN27 = 27   # button 0
PIN29 = 29   # button 1
PIN31 = 31   # LED 0
PIN33 = 33    # LED 1


gpio31 =-1
gpio33 =-1

class DPS:
    def __init__(self):
        self.bus = smbus2.SMBus(I2C_BUS)  # Initialize the I2C bus
        self.addr = self.find_address()  # Find the I2C address of the sensor
        self.__correctTemperature()  # Correct temperature calibration
        self.__setOversamplingRate()  # Set oversampling rate

    def find_address(self):
        # Try to find the sensor on known addresses
        for address in DPS310_ADDRESSES:
            try:
                self.bus.read_byte(address)
                return address
            except IOError:
                continue
        raise Exception("DPS310 sensor not found on any known address")

    def getTwosComplement(self, raw_val, length):
        # Calculate two's complement for signed integer representation
        val = raw_val
        if raw_val & (1 << (length - 1)):
            val = raw_val - (1 << length)
        return val

    def __correctTemperature(self):
        # Correct the temperature readings
        self.bus.write_byte_data(self.addr, 0x0E, 0xA5)
        self.bus.write_byte_data(self.addr, 0x0F, 0x96)
        self.bus.write_byte_data(self.addr, 0x62, 0x02)
        self.bus.write_byte_data(self.addr, 0x0E, 0x00)
        self.bus.write_byte_data(self.addr, 0x0F, 0x00)

    def __setOversamplingRate(self):
        # Set the oversampling rate for temperature and pressure readings
        self.bus.write_byte_data(self.addr, 0x06, 0x26)
        self.bus.write_byte_data(self.addr, 0x07, 0xA6)
        self.bus.write_byte_data(self.addr, 0x08, 0x07)
        self.bus.write_byte_data(self.addr, 0x09, 0x0C)

    def __getRawTemperature(self):
        # Read raw temperature data from the sensor
        t1 = self.bus.read_byte_data(self.addr, 0x03)
        t2 = self.bus.read_byte_data(self.addr, 0x04)
        t3 = self.bus.read_byte_data(self.addr, 0x05)
        t = (t1 << 16) | (t2 << 8) | t3
        t = self.getTwosComplement(t, 24)
        return t

    def __getRawPressure(self):
        # Read raw pressure data from the sensor
        p1 = self.bus.read_byte_data(self.addr, 0x00)
        p2 = self.bus.read_byte_data(self.addr, 0x01)
        p3 = self.bus.read_byte_data(self.addr, 0x02)
        p = (p1 << 16) | (p2 << 8) | p3
        p = self.getTwosComplement(p, 24)
        return p

    def calcScaledTemperature(self):
        # Calculate scaled temperature
        raw_t = self.__getRawTemperature()
        scaled_t = raw_t / 1040384  # __kT = 1040384
        return scaled_t

    def calcCompTemperature(self, scaled_t):
        # Calculate compensated temperature
        c0, c1 = self.__getTemperatureCalibrationCoefficients()
        comp_t = c0 * 0.5 + scaled_t * c1
        return comp_t

    def calcScaledPressure(self):
        # Calculate scaled pressure
        raw_p = self.__getRawPressure()
        scaled_p = raw_p / 1040384  # __kP = 1040384
        return scaled_p

    def calcCompPressure(self, scaled_p, scaled_t):
        # Calculate compensated pressure
        c00, c10, c20, c30, c01, c11, c21 = self.__getPressureCalibrationCoefficients()
        comp_p = (c00 + scaled_p * (c10 + scaled_p * (c20 + scaled_p * c30))
                  + scaled_t * (c01 + scaled_p * (c11 + scaled_p * c21)))
        return comp_p

    def __getTemperatureCalibrationCoefficients(self):
        # Get temperature calibration coefficients from the sensor
        src10 = self.bus.read_byte_data(self.addr, 0x10)
        src11 = self.bus.read_byte_data(self.addr, 0x11)
        src12 = self.bus.read_byte_data(self.addr, 0x12)
        c0 = (src10 << 4) | (src11 >> 4)
        c0 = self.getTwosComplement(c0, 12)
        c1 = ((src11 & 0x0F) << 8) | src12
        c1 = self.getTwosComplement(c1, 12)
        return c0, c1

    def __getPressureCalibrationCoefficients(self):
        # Get pressure calibration coefficients from the sensor
        src13 = self.bus.read_byte_data(self.addr, 0x13)
        src14 = self.bus.read_byte_data(self.addr, 0x14)
        src15 = self.bus.read_byte_data(self.addr, 0x15)
        src16 = self.bus.read_byte_data(self.addr, 0x16)
        src17 = self.bus.read_byte_data(self.addr, 0x17)
        src18 = self.bus.read_byte_data(self.addr, 0x18)
        src19 = self.bus.read_byte_data(self.addr, 0x19)
        src1A = self.bus.read_byte_data(self.addr, 0x1A)
        src1B = self.bus.read_byte_data(self.addr, 0x1B)
        src1C = self.bus.read_byte_data(self.addr, 0x1C)
        src1D = self.bus.read_byte_data(self.addr, 0x1D)
        src1E = self.bus.read_byte_data(self.addr, 0x1E)
        src1F = self.bus.read_byte_data(self.addr, 0x1F)
        src20 = self.bus.read_byte_data(self.addr, 0x20)
        src21 = self.bus.read_byte_data(self.addr, 0x21)

        c00 = (src13 << 12) | (src14 << 4) | (src15 >> 4)
        c00 = self.getTwosComplement(c00, 20)

        c10 = ((src15 & 0x0F) << 16) | (src16 << 8) | src17
        c10 = self.getTwosComplement(c10, 20)

        c20 = (src1C << 8) | src1D
        c20 = self.getTwosComplement(c20, 16)

        c30 = (src20 << 8) | src21
        c30 = self.getTwosComplement(c30, 16)

        c01 = (src18 << 8) | src19
        c01 = self.getTwosComplement(c01, 16)

        c11 = (src1A << 8) | src1B
        c11 = self.getTwosComplement(c11, 16)

        c21 = (src1E << 8) | src1F
        c21 = self.getTwosComplement(c21, 16)

        return c00, c10, c20, c30, c01, c11, c21

    def read_temperature(self):
        # Read and return the compensated temperature
        scaled_t = self.calcScaledTemperature()
        temperature = self.calcCompTemperature(scaled_t)
        return temperature

    def read_pressure(self):
        # Read and return the compensated pressure
        scaled_t = self.calcScaledTemperature()
        scaled_p = self.calcScaledPressure()
        pressure = self.calcCompPressure(scaled_p, scaled_t)
        return pressure

class PA_CO2:
    def __init__(self, device_address=0x28, period=10000):
        self.device_address = device_address  # Set device address
        self.period = period  # Set measurement period
        self.bus = smbus2.SMBus(1)  # Initialize the I2C bus
        
    def read_byte(self, command):
        # Read a byte from the given command register
        return self.bus.read_byte_data(self.device_address, command)
    
    def write_byte(self, command, value):
        # Write a byte to the given command register
        self.bus.write_byte_data(self.device_address, command, value)
    
    def check_sensor_status(self):
        # Check the sensor status
        status = self.read_byte(0x01)
        return status
    
    def set_idle_mode(self):
        # Set the sensor to idle mode
        self.write_byte(0x04, 0x00)
        time.sleep(0.4)
    
    def set_pressure(self, high_byte=0x03, low_byte=0xF5):
        # Set the pressure compensation
        self.write_byte(0x0B, high_byte)
        self.write_byte(0x0C, low_byte)
    
    def trigger_measurement(self):
        # Trigger a CO2 measurement
        self.write_byte(0x04, 0x01)
        time.sleep(1.15)
    
    def get_ppm_value(self):
        # Get the CO2 concentration in ppm
        value1 = self.read_byte(0x05)
        time.sleep(0.005)
        value2 = self.read_byte(0x06)
        time.sleep(0.005)
        result = (value1 << 8) | value2
        return result
    
    def measure_co2(self):
        # Measure CO2 concentration and return the value in ppm
        self.set_idle_mode()
        self.set_pressure()
        self.trigger_measurement()
        ppm = self.get_ppm_value()
        return ppm

class SensorHTTPServer(BaseHTTPRequestHandler):
    dps = DPS()  # Initialize the DPS sensor
    co2_sensor = PA_CO2()  # Initialize the CO2 sensor
    web_ui = None  # Class variable to hold reference to WebUI instance
    historical_data = {
        'temperature': [],
        'pressure': [],
        'co2': [],
        'date_time': [],
        'gpio35': [],
        'gpio36': [],
        'gpio27': [],
        'gpio29': [],
        'gpio31': [],
        'gpio33': []
    }
    
    @classmethod
    def set_web_ui(cls, ui_instance):
        # Set the WebUI instance
        cls.web_ui = ui_instance

    def _set_headers(self):
        # Set HTTP headers
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def do_GET(self): 

        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        # Handle GPIO settings
        if 'gpio31' in query_params:
            if query_params['gpio31'][0] == '0':
                GPIO.output(31, GPIO.LOW)
            elif query_params['gpio31'][0] == '1':
                GPIO.output(31, GPIO.HIGH)
        
        if 'gpio33' in query_params:
            if query_params['gpio33'][0] == '0':
                GPIO.output(33, GPIO.LOW)
            elif query_params['gpio33'][0] == '1':
                GPIO.output(33, GPIO.HIGH)

        # Handle data queries
        query = query_params.get('q', [None])[0]
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')


        if query == 'all':
            data = self.handle_all()
        elif query == 'temperature':
            temperature = self.dps.read_temperature()
            data = {'temperature': temperature, 'date_time': current_time}
        elif query == 'pressure':
            pressure = self.dps.read_pressure()
            data = {'pressure': pressure, 'date_time': current_time}
        elif query == 'co2':
            co2_ppm = self.co2_sensor.measure_co2()
            data = {'co2': co2_ppm, 'date_time': current_time}
        elif query == 'distance':
            data = self.handle_distance()
        elif query == 'dashboard':
            self.handle_dashboard()
            return
        elif query == 'history':
            data = self.handle_history()
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <head><title>Sensor Data Service</title></head>
                <body>
                    <h1>Sensor Data Service</h1>
                    <p>Use the following queries to get data:</p>
                    <ul>
                        <li><a href="/?q=all">All data</a></li>
                        <li><a href="/?q=temperature">Temperature data</a></li>
                        <li><a href="/?q=pressure">Pressure data</a></li>
                        <li><a href="/?q=co2">CO2 data</a></li>
                        <li><a href="/?q=distance">Distance data</a></li>
                        <li><a href="/?q=all&gpio31=1&gpio33=1">led0 off, led1 off</a></li>
                        <li><a href="/?q=all&gpio31=0&gpio33=0">led0 on, led1 on</a></li>
                        <li><a href="/?q=history">History data</a></li>
                        <li><a href="/?q=dashboard">Dashboard</a></li>
                    </ul>
                </body>
                </html>
            """)
            return

        self._set_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
        
    def do_GET2(self):
        # Handle GET requests
        query = self.path.split('=')[-1] if '=' in self.path else None        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if query == 'all':
            data = self.handle_all()
        elif query == 'temperature':
            temperature = self.dps.read_temperature()
            data = {'temperature': temperature, 'date_time': current_time}
        elif query == 'pressure':
            pressure = self.dps.read_pressure()
            data = {'pressure': pressure, 'date_time': current_time}
        elif query == 'co2':
            co2_ppm = self.co2_sensor.measure_co2()
            data = {'co2': co2_ppm, 'date_time': current_time}
        elif query == 'distance':
            data = self.handle_distance()
        elif query == 'dashboard':
            self.handle_dashboard()
            return
        elif query == 'history':
            data = self.handle_history()
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            # Inside the relevant handler or function that generates the HTML response
            self.wfile.write(b"""
                <html>
                <head><title>Sensor Data Service</title></head>
                <body>
                    <h1>Sensor Data Service</h1>
                    <p>Use the following queries to get data:</p>
                    <ul>
                        <li><a href="/?q=all">All data</a></li>
                        <li><a href="/?q=temperature">Temperature data</a></li>
                        <li><a href="/?q=pressure">Pressure data</a></li>
                        <li><a href="/?q=co2">CO2 data</a></li>
                        <li><a href="/?q=distance">Distance data</a></li>
                        <li><a href="/?q=history">History data</a></li>
                        <li><a href="/?q=dashboard">Dashboard</a></li>
                    </ul>
                </body>
                </html>
            """)

            return
        
        self._set_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def _set_headers(self):
        # Set HTTP headers for HTML responses
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def handle_file(self):
        # Handle requests for the dashboard HTML page
        self._set_headers()
        try:
            with open('dashboard.html', 'rb') as file:
                self.wfile.write(file.read())
        except FileNotFoundError:
            self.send_response(404)
            self.wfile.write(b"404 Not Found: dashboard.html file is missing")
            
    def handle_dashboard(self):
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(dashboard_content.encode('utf-8'))
        
    def handle_all(self):
        # Handle requests for all sensor data
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        temperature = self.dps.read_temperature()
        pressure = self.dps.read_pressure()
        co2_ppm = self.co2_sensor.measure_co2()
        gpio35 = GPIO.input(PIN35)
        gpio36 = GPIO.input(PIN36)
        gpio27 = -1 #GPIO.input(PIN27)
        gpio29 = GPIO.input(PIN29)
        




 
        data = {
                'temperature': temperature,
                'pressure': pressure,
                'co2': co2_ppm,
                'gpio35': gpio35,
                'gpio36': gpio36,
                'gpio27': gpio27,
                'gpio29': gpio29,
                'gpio31': gpio31,
                'gpio33': gpio33,
                'date_time': current_time
        }
            
        # Update historical data
        self.historical_data['temperature'].append(temperature)
        self.historical_data['pressure'].append(pressure)
        self.historical_data['co2'].append(co2_ppm)
        self.historical_data['gpio35'].append(gpio35)
        self.historical_data['gpio36'].append(gpio36)
        self.historical_data['gpio27'].append(gpio27)
        self.historical_data['gpio29'].append(gpio29)
        self.historical_data['gpio31'].append(gpio31)
        self.historical_data['gpio33'].append(gpio33)
        self.historical_data['date_time'].append(current_time)

        # Ensure only the last 50 records are kept
        if len(self.historical_data['temperature']) > 50:
            self.historical_data['temperature'].pop(0)
            self.historical_data['pressure'].pop(0)
            self.historical_data['co2'].pop(0)
            self.historical_data['gpio35'].pop(0)
            self.historical_data['gpio36'].pop(0)
            self.historical_data['gpio27'].pop(0)
            self.historical_data['gpio29'].pop(0)
            self.historical_data['gpio31'].pop(0)
            self.historical_data['gpio33'].pop(0)
            self.historical_data['date_time'].pop(0)

        return data

    def handle_history(self):
        # Handle requests for historical data
        historical_data = {
            'temperature': self.historical_data['temperature'],
            'pressure': self.historical_data['pressure'],
            'co2': self.historical_data['co2'],
            'gpio27': self.historical_data['gpio27'],
            'gpio29': self.historical_data['gpio29'],
            'gpio31': self.historical_data['gpio31'],
            'gpio33' : self.historical_data['gpio33'],
            'gpio35': self.historical_data['gpio35'],
            'gpio36': self.historical_data['gpio36'],
            'date_time': self.historical_data['date_time']
        }
        return historical_data
    
    def handle_distance(self):
        # Handle requests for GPIO pin data
        gpio35 = GPIO.input(PIN35)  # distance 0
        gpio36 = GPIO.input(PIN36) # distance 1
        gpio27 = GPIO.input(PIN27)  # button 0
        gpio29 = GPIO.input(PIN29) # button 1
        data = {
            'gpio35': gpio35,
            'gpio36': gpio36,
            'gpio27': gpio27,
            'gpio29': gpio29,
            'date_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        return data

    def log_message(self, format, *args):
        # Log HTTP server messages
        message = f"{self.address_string()} - - [{self.log_date_time_string()}] {format % args}"
        print(message)
        if self.web_ui:
            self.web_ui.update_log(message)

class WebUI:
    def __init__(self, private_ip, public_ip):
        self.private_ip = private_ip  # Private IP address
        self.public_ip = public_ip  # Public IP address

        self.root = Tk()
        self.root.title("Sensor HTTP Server Info")

        self.create_widgets()

    def create_widgets(self):
        # Create UI elements
        Label(self.root, text=f"Private IP: {self.private_ip}:{PORT}").pack()        
        self.copy_private_ip_button = Button(self.root, text="Copy Private IP", command=self.copy_private_ip)
        self.copy_private_ip_button.pack()
        
        Label(self.root, text=f"Public IP: {self.public_ip}:{PORT}").pack()
        self.copy_public_ip_button = Button(self.root, text="Copy Public IP", command=self.copy_public_ip)
        self.copy_public_ip_button.pack()
        
        # Create QR code for the IP address
        url = f"http://{self.private_ip}:{PORT}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill="black", back_color="white")
        # qr_img = qr_img.resize((100, 100), Image.ANTIALIAS)  # Resize to 100x100 pixels
        qr_img = qr_img.resize((100, 100), Image.LANCZOS)

        qr_img_bytes = io.BytesIO()
        qr_img.save(qr_img_bytes, format="PNG")
        qr_img_bytes.seek(0)
        self.qr_photo = PhotoImage(data=qr_img_bytes.read())

        qr_label = Label(self.root, image=self.qr_photo)
        qr_label.pack()

        self.log_text = Text(self.root, wrap='word', height=10, width=50)
        self.log_text.pack()

        scrollbar = Scrollbar(self.root, orient=VERTICAL, command=self.log_text.yview)
        self.log_text['yscrollcommand'] = scrollbar.set
        scrollbar.pack(side='right', fill='y')

    def update_log(self, message):
        # Update the log text in the UI
        self.log_text.insert(END, f"{message}\n")
        self.log_text.yview(END)

    def copy_private_ip(self):
        # Copy private IP address to clipboard
        pyperclip.copy(f"http://{self.private_ip}:{PORT}")
        self.update_log("Private IP copied to clipboard")

    def copy_public_ip(self):
        # Copy public IP address to clipboard
        pyperclip.copy(f"http://{self.public_ip}:{PORT}")
        self.update_log("Public IP copied to clipboard")

    def run(self):
        # Run the Tkinter main loop
        self.root.mainloop()

def get_private_ip():
    # Get the private IP address of the machine
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip

def get_public_ip():
    # Get the public IP address of the machine
    return requests.get('https://api.ipify.org').text

def run_server():
    # Run the HTTP server
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, SensorHTTPServer)
    print(f"Starting HTTP server on {private_ip}:{PORT}")
    SensorHTTPServer.web_ui.update_log(f"Starting HTTP server on {private_ip}:{PORT}")
    httpd.serve_forever()

if __name__ == "__main__":
    private_ip = get_private_ip()
    public_ip = get_public_ip()

        
    # Setup GPIO pins
    GPIO.setwarnings(False) 
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(PIN35, GPIO.IN)
    GPIO.setup(PIN36, GPIO.IN)
    # GPIO.setup(PIN27, GPIO.IN)# button 0
    GPIO.setup(PIN29, GPIO.IN)# button 1
    GPIO.setup(PIN31, GPIO.OUT)   # LED 0
    GPIO.setup(PIN33, GPIO.OUT)    # LED 1



    # Start the Tkinter GUI
    web_ui = WebUI(private_ip, public_ip)
    SensorHTTPServer.set_web_ui(web_ui)  # Set the WebUI instance to the HTTP server

    # Start the web server in a separate thread
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()

    # Run the Tkinter main loop
    web_ui.run()


dashboard_content = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Dashboard</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
                <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
                <script type="text/javascript" src="https://www.gstatic.com/charts/loader.js"></script>
                <script type="text/javascript">
                    google.charts.load('current', {'packages':['corechart']});
                    google.charts.setOnLoadCallback(initDashboard);

                    var temperatureData = [['Time', 'Temperature']];
                    var pressureData = [['Time', 'Pressure']];
                    var co2Data = [['Time', 'CO2']];
                    var gpioData = [['Time', 'GPIO 35', 'GPIO 36']];
                    var intervalId;
                    var fetchInterval = 5000; // Default interval of 5 seconds

                    function initDashboard() {
                        $('#intervalDropdown').val(fetchInterval);
                        $('#intervalDropdown').change(function() {
                            fetchInterval = $(this).val();
                            clearInterval(intervalId);
                            intervalId = setInterval(fetchData, fetchInterval);
                        });

                        fetchData();
                        intervalId = setInterval(fetchData, fetchInterval);
                    }

                    function fetchData() {
                        $.getJSON("/?q=all", function(data) {
                            updateChartData(temperatureData, data.temperature, data.date_time, 'temperature_chart', 'Temperature History', 'latest_temperature');
                            updateChartData(pressureData, data.pressure, data.date_time, 'pressure_chart', 'Pressure History', 'latest_pressure');
                            updateChartData(co2Data, data.co2, data.date_time, 'co2_chart', 'CO2 History', 'latest_co2');
                            updateGPIOData(gpioData, data.gpio35, data.gpio36, data.date_time, 'gpio_chart', 'GPIO Pins History', 'latest_gpio');
                        });
                    }

                    function updateChartData(chartData, newData, currentTime, elementId, title, latestElementId) {
                        var time = currentTime.split(' ')[1];

                        chartData.push([time, newData]);
                        if (chartData.length > 51) {
                            chartData.splice(1, 1); // Remove the oldest data point
                        }

                        var dataTable = google.visualization.arrayToDataTable(chartData);
                        var options = {
                            title: title,
                            curveType: 'function',
                            legend: { position: 'bottom' }
                        };
                        var chart = new google.visualization.LineChart(document.getElementById(elementId));
                        chart.draw(dataTable, options);

                        document.getElementById(latestElementId).innerText = `Latest Value: ${newData} at ${currentTime}`;
                    }

                    function updateGPIOData(chartData, newGpio35, newGpio36, currentTime, elementId, title, latestElementId) {
                        var time = currentTime.split(' ')[1];

                        chartData.push([time, newGpio35, newGpio36]);
                        if (chartData.length > 51) {
                            chartData.splice(1, 1); // Remove the oldest data point
                        }

                        var dataTable = google.visualization.arrayToDataTable(chartData);
                        var options = {
                            title: title,
                            curveType: 'function',
                            legend: { position: 'bottom' }
                        };
                        var chart = new google.visualization.LineChart(document.getElementById(elementId));
                        chart.draw(dataTable, options);

                        document.getElementById(latestElementId).innerText = `Latest Values: GPIO 35: ${newGpio35}, GPIO 36: ${newGpio36} at ${currentTime}`;
                    }
                </script>
            </head>
            <body>
                <div class="container mt-5">
                    <h1 class="mb-4">Dashboard</h1>
                    <div class="row mb-3">
                        <div class="col-md-3">
                            <label for="intervalDropdown" class="form-label">Fetch Interval (seconds)</label>
                            <select id="intervalDropdown" class="form-select">
                                <option value="1000">1</option>
                                <option value="2000">2</option>
                                <option value="3000">3</option>
                                <option value="4000">4</option>
                                <option value="5000" selected>5</option>
                                <option value="10000">10</option>
                                <option value="15000">15</option>
                            </select>
                        </div>
                    </div>        
                    <hr>
                    <div class="row">
                        <div class="col-md-12">
                            <h2>Temperature</h2>
                            <p id="latest_temperature" class="text-center"></p>
                            <div id="temperature_chart" style="width: 100%; height: 500px;"></div>
                            <hr>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-12">
                            <h2>Pressure</h2>
                            <p id="latest_pressure" class="text-center"></p>
                            <div id="pressure_chart" style="width: 100%; height: 500px;"></div>
                            <hr>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-12">
                            <h2>Co2</h2>
                            <p id="latest_co2" class="text-center"></p>
                            <div id="co2_chart" style="width: 100%; height: 500px;"></div>
                            <hr>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-12">
                            <h2>GPIO Pins</h2>
                            <p id="latest_gpio" class="text-center"></p>
                            <div id="gpio_chart" style="width: 100%; height: 500px;"></div>
                            <hr>
                        </div>
                    </div>
                    <footer class="text-center mt-4">
                        <p>1999 - 2024 Infineon Technologies AG ,  GPL v2, Developer: Powen Ko</p>
                    </footer>
                </div>

                <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
            </body>
            </html>
            """

