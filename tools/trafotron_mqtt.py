#!/usr/bin/env python3
# -*- coding: utf-8 -*- 

import time
from threading import Thread
import copy
import json
import requests
from colorsys import hsv_to_rgb
from http.server import HTTPServer, BaseHTTPRequestHandler
from pylibcerebrum.serial_mux import SerialMux

import paho.mqtt.client as paho

CBEAM			= 'http://c-beam.cbrp3.c-base.org:4254/rpc/'
MQTT_SERVER             = 'c-beam.cbrp3.c-base.org'
MQTT_PORT               = 1883
MQTT_USER               = 'trafotron'
HYPERBLAST		= 'http://10.0.1.23:1337/'
CLOCC			= 'http://c-lab-lock.cbrp3.c-base.org:1337/'
PORT			= '/dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_7523230313535161C072-if00'
BAUDRATE		= 115200
AVG_SAMPLES		= 128
SEND_THRESHOLD	= 3

mqtt = paho.Client(MQTT_USER)

s = SerialMux(PORT, BAUDRATE)
print('discovering cerebrum devices')
results = []
while not results:
	results = s.discover()
print(results)
print('opening first device')
g = s.open(0)
print('initializing device')
print(dir(g))
#bar status outputs
for io in [g.digital3, g.digital5, g.digital6, g.digital9, g.digital10, g.digital11]:
	io.direction = 1
	io.pwm_enabled = 1
print('starting event loop')

oldre, oldge, oldgn = None,None,None
def ampel(re,ge,gn):
	global oldre, oldge, oldgn
	if re and ge and gn:
		gn = False
	# Ensure no more than two lights are on at the same time, even for very short periods of time
	if oldre != re:
		g.ampelrot.state  = re
	if oldge != ge:
		g.ampelgelb.state = ge
	if oldgn != gn:
		g.ampelgrün.state = gn
	oldre,oldge,oldgn = re,ge,gn

#HACK ctrl-c ctrl-p -ed from barstatus.py
barstatus = 'closed'
ampelstate = ((0,0,0), (0,0,0))
lastchange = time.time() - 180
def animate():
	global barstatus, lastchange, ampelstate, g
	hue = 0
	while True:
		if barstatus == 'google-zahlt':
			_r,_g,_b = hsv_to_rgb(hue, 1, 1)
			c = (int(_r*255), int(_g*255), int(_b*255))
			(g.digital3.pwm, g.digital5.pwm, g.digital6.pwm), (g.digital9.pwm, g.digital10.pwm, g.digital11.pwm) = c, (0,0,0)
			hue += 0.05
			time.sleep(0.1)
			continue
		lookup = barstatus
		if time.time() - lastchange < 180:
			if barstatus == 'open':
				lookup = 'opened'
			elif barstatus == 'closed':
				lookup = 'lastcall'
		l1, r1 = {'open': ((10, 255, 10), (128, 128, 128)),
			'opened': ((10, 128, 255), (128, 128, 128)),
			'closed': ((128, 128, 128), (255, 4, 4)),
		      'lastcall': ((10, 255, 10), (128, 128, 128))}.get(lookup)
		l2, r2 = {'open': ((10, 255, 10), (128, 128, 128)),
			'opened': ((10, 255, 10), (128, 128, 128)),
			'closed': ((128, 128, 128), (255, 4, 4)),
		      'lastcall': ((10, 255, 10), (255, 255, 10))}.get(lookup)
		(g.digital3.pwm, g.digital5.pwm, g.digital6.pwm), (g.digital9.pwm, g.digital10.pwm, g.digital11.pwm) = l1, r1
		ampel(*ampelstate[0])
		time.sleep(0.33)
		(g.digital3.pwm, g.digital5.pwm, g.digital6.pwm), (g.digital9.pwm, g.digital10.pwm, g.digital11.pwm) = l2, r2
		ampel(*ampelstate[1])
		time.sleep(0.66)

animator = Thread(target=animate)
animator.daemon = True
animator.start()


def sendstate(value):
	print('SENDING', value)
	try:
		requests.post(CBEAM, data=json.dumps({'method': 'trafotron', 'params': [value], 'id': 0}))
	except requests.exceptions.ConnectionError:
		pass

def publish(topic, payload):
    try:
        #mqtt.username_pw_set(MQTT_USER, password=MQTT_PASS)
        #if cfg.mqtt_server_tls:
            #mqtt.tls_set(cfg.mqtt_server_cert, cert_reqs=ssl.CERT_OPTIONAL)
            #mqtt.connect(cfg.mqtt_server, port=1884)
        #else:
            #mqtt.connect(cfg.mqtt_server, port=1883)
        mqtt.connect(MQTT_SERVER, port=MQTT_PORT)
        mqtt.publish(topic, payload)
    except Exception as e:
        print(e)
        pass

class AmpelHandler(BaseHTTPRequestHandler):
	def do_POST(self):
		global ampelstate
		self.send_response(200)
		self.end_headers()
		postlen = int(self.headers['Content-Length'])
		postdata = str(self.rfile.read(postlen), 'utf-8')
		data = json.loads(postdata)
		method = data.get('method')
		if method == 'ampel':
			p = data.get('params')
			if type(p[0]) is list:
				(r1,y1,g1),(r2,y2,g2) = p
				r1,y1,g1 = bool(r1), bool(y1), bool(g1)
				r2,y2,g2 = bool(r2), bool(y2), bool(g2)
				ampelstate = ((r1,y1,g1),(r2,y2,g2))
			elif type(p[0]) is int and len(p) == 1:
				a,b = (bool(p[0]&32), bool(p[0]&16), bool(p[0]&8)), (bool(p[0]&4), bool(p[0]&2), bool(p[0]&1))
				ampelstate = a,b
			else:
				r,y,g = p
				r,y,g = bool(r), bool(y), bool(g)
				ampelstate = (r,y,g), (r,y,g)

HOST, PORT = '', 1337
server = HTTPServer((HOST, PORT), AmpelHandler)
t = Thread(target=server.serve_forever)
t.daemon = True
t.start()

time.sleep(2)

# Enable pull-up on Arduino analog pin 4
g.analog4.state = 1
g.digital2.state = 1
g.digital12.state = 1
g.digital13.state = 1
oldval = -2*SEND_THRESHOLD
oldbarstate = None
newbarstate = None
oldstrippen = None
while True:
	val = sum([ g.analog5.analog for i in range(AVG_SAMPLES)])/AVG_SAMPLES
	if abs(val-oldval) > SEND_THRESHOLD:
		oldval = val
		sendstate(int(val))
	if g.analog4.state:
		newbarstate = 'closed'
	else:
		newbarstate = 'open'
	strippen = (g.digital2.state, g.digital12.state, g.digital13.state)
	if strippen != oldstrippen:
		oldstrippen = strippen
		publish('bar/strippen', json.dumps({'method': 'barschnur', 'params': list(strippen), 'id': 0}))
		#try:
			#requests.post(CBEAM, data=json.dumps({'method': 'barschnur', 'params': list(strippen), 'id': 0}))
		#except requests.exceptions.ConnectionError:
			#pass
	if newbarstate != oldbarstate:
		oldbarstate = newbarstate

		#comm with animation thread
		barstatus = newbarstate
		lastchange = time.time()
		publish('bar/status', json.dumps({'method': 'barstatus', 'params': [newbarstate], 'id': 0}))

		try:
			requests.post(HYPERBLAST, data=json.dumps({'method': 'barstatus', 'params': [newbarstate], 'id': 0}))
		except requests.exceptions.ConnectionError:
			pass
		try:
			requests.post(CBEAM, data=json.dumps({'method': 'barstatus', 'params': [newbarstate], 'id': 0}))
		except requests.exceptions.ConnectionError:
			pass
		try:
			requests.post(CLOCC, data=json.dumps({'method': 'barstatus', 'params': [newbarstate], 'id': 0}))
		except requests.exceptions.ConnectionError:
			pass

