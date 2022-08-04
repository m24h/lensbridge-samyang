import serial
import sys, threading, time, struct
import signal

# just emulate am AF45/1.8, no need to connect to a real lens
EMULATE_AF4518=False
# don't do firmware downloading/updating, just want to adjust some parameters
DONT_TOUCH_FW=True
# if last firmware updating failed, lens stays in bootloading
FIXFW=False
# when downloding, flash cleaning will result in timeout of Lens Manager
# this can be set only when flash cleaning is done before at least once 
SKIP_FLASH_CLEAN=False
# when downloding, packets printing will result in timeout of Lens Manager
PRINT_FW_DATA=True  

PORT_LENS="COM4"
PORT_BROKER="COM5"

'''
	to use this script, a back-to-back virtual serial port pair is needed. 
	for example, a virtual serial port pair like COM5<->COM6 can be setup by "COM0COM" tool,
	then let "Sanyang Lens Manager" open COM6, 
	and this script should open COM5 and listen requests, 
	translate/transfer to lens, translate/transfer response back to COM5.
	
	to connect to a real lens, a USB-serial hardware is needed, and it should support 750kHz baudrate, like ch340G.
	face to the tail of lens (on which side electronic pins exist),
	rotate the lens keeping the electronic pins on bottom side,
	then the pins from left to right are (excluding 2 fake pins on the most left side):
		Gnd, Vcc-Drive, Gnd, body_vd_lens, Vcc, lens_cs_body, lens_data_body, body_data_lens, body_cs_lens, lens_detect
	connections from USB-serial hardware to lens:
		Gnd <-> Gnd
		5V   <-> Vcc-Drive
		Gnd <-> Gnd
		DTR <-> body_vd_lens
		3.1V <-> Vcc
		RXD <-> lens_data_body
		TXD <-> body_data_lens
		RTS <-> body_cs_lens

	a stable 5V Vcc-Drive is needed, some functions need to reset focus/aperture of lens before going on.

'''


ser_lens=None
ser_broker=None
vd_sync=False
prn_pkt=True

def vd():
	while True:
		if (not EMULATE_AF4518) and vd_sync:
			ser_lens.dtr=1
			ser_lens.dtr=0
		time.sleep(0.02)
				
def bsend(b):
	s=b'\x02'+b+b'\x0D\x0A'
	ser_broker.write(s)
	if prn_pkt:
		print ('B S:', s.hex(' '))
	
def brecv():
	global prn_pkt
	ser_broker.read_until(b'\x02')
	s=ser_broker.read_until(b'\x0D\x0A')
	if s[2:3]==b'\xF0':
		size=struct.unpack('<H',s[3:5])[0]
		if len(s)<size+2+2:
			s+=ser_broker.read(size+2+2-len(s))
	if s[0:2]==b'B\x03':
		prn_pkt=PRINT_FW_DATA 
	else:
		prn_pkt=True
	if prn_pkt:
		print('============================')
		print ('B R: 02', s.hex(' '))	
	return s		

def lsend(b, size=0, type=2, seq=0):
	if size>0:
		b+=b'\x00'*(size-len(b))
	else:
		size=len(b)
	size+=1+4+3
	cksum=(size>>8)+(size & 0xff)+type+seq
	for x in b:
		cksum+=x
	s=struct.pack('<BHBB', 0xF0, size, type, seq)+b+struct.pack('<HB',cksum,0x55)
	ser_lens.rts=0
	ser_lens.write(s)
	ser_lens.rts=1
	if prn_pkt:
		print ('L S:', s.hex(' '))

def lsendB(cmd1, s):
	if s[0:1]==b'\xF0':
		size=struct.unpack('<H', s[1:3])[0]
		s=s[0:size]
		ser_lens.rts=0
		ser_lens.write(s)
		ser_lens.rts=1
		if prn_pkt:
			print ('L S:', s.hex(' '))
	else:	
		lsend(b'\x40B'+cmd1, 11)

def lrecv(wait=b'', timeout=None):
	while True:
		ser_lens.timeout=timeout
		som=ser_lens.read_until(b'\xF0')
		ser_lens.timeout=None
		if len(som)<1:
			return None
		head=ser_lens.read(4)
		(size, type, seq)=struct.unpack("<HBB", head)
		if size<9:
			continue
		s=ser_lens.read(size-8)
		tail=ser_lens.read(2)
		cksum=struct.unpack("<H", tail)[0]
		eom=ser_lens.read(1)
		if eom!=b'\x55':
			continue
		if prn_pkt:
			print ('L R: F0', head.hex(' '), s.hex(' '), tail.hex(' '), eom.hex())
		if s.startswith(wait):
			return s

def b2l2b():
	global vd_sync

	while True:
		s=brecv()
		cmd=s[0:1]
		s=s[1:len(s)-2]
		
		if cmd==b'M':  #20,1,35,3
			print ("--- lens model get ---")
			if EMULATE_AF4518:
				bsend(b'M45')
				continue
			lsend(b'\x40M', 19)
			s=lrecv(b'\x40M')
			bsend(b'M%d' % s[3])
			
		elif cmd==b'K': #20,1,39,5
			print ("--- product ID get ---")
			if EMULATE_AF4518:
				bsend(b's12345678\x00')
				continue			
			lsend(b'\x40K\xFA', 19)
			s=lrecv(b'\x40K\xFA')
			bsend(s[3:13])
			
		elif cmd==b'V': #20,1,37,4
			print ("--- lens firmware version get ---")
			if EMULATE_AF4518:
				bsend(b'V0101')
				continue			
			lsend(b'\x40V', 19)
			s=lrecv(b'\x40V')
			bsend(b'V%02d%02d' % (s[3],s[4]))
						
		elif cmd==b'G':  # 20,12,32,15
			print ("--- dock firmware version get ---") 
			bsend(b'G100')
			
		elif cmd==b'X':
			cmd1=s[0:1]
			s=s[1:]
			if cmd1==b'4': #20,13,32,64,F1
				print ("--- enter bootloader ---")
				if EMULATE_AF4518 or DONT_TOUCH_FW:
					bsend(b'A')
					continue				
				lsend(b'\x40X4'+struct.pack('B', int(s[1:])), 19)
				bsend(b'A')
			elif cmd1==b'2':  #20,1,32,2   20,2,32,2  20,22,,2
				print ("--- lens reset 2---")
				if EMULATE_AF4518:
					bsend(b'A')
					continue
				lsend(b'\x40X2', 19)
				bsend(b'A')
			elif cmd1==b'B':  #20,1,33,1
				print ("--- lens reset B ---")
				if EMULATE_AF4518:
					bsend(b'A')
					continue
				lsend(b'\x40XB', 19)
				bsend(b'A')
			else:
				print ("!!! X unknown %02x !!!" % cmd1[0])
				bsend(b'F')
			
		elif cmd==b'F':
			cmd1=s[0:1]
			s=s[1:]
			vd_sync=True
			if cmd1==b'5':
				if len(s)>0:  #20,4,32,7 20,17,34,17 20,17,36,18  20,17,38,19  20,17,40,20
					print ("--- AF Punt set ---")
					if EMULATE_AF4518:
						bsend(b'A')
						continue
					lsend(b'\x40F\xCB'+struct.pack('B', int(s[1:])), 19)
					t=lrecv(b'\x40F\xCB', timeout=1)
					bsend(b'A')
				else:    #20,1,41,6   20,3,32,6  20,16,34,6
					print ("--- AF punt get ---") 
					if EMULATE_AF4518:
						bsend(b'1')
						continue
					lsend(b'\x40F\xCA', 19)
					t=lrecv(b'\x40F\xCA', timeout=1)
					bsend(b'%d' % t[3])
			elif cmd1==b'6':
				if len(s)>0: #20,6,32,9
					print ("--- MF sense set ---")
					if EMULATE_AF4518:
						bsend(b'A')
						continue					
					lsend(b'\x40F\xBB'+struct.pack('B', int(s[1:])), 19)
					t=lrecv(b'\x40F\xBB', timeout=1)
					bsend(b'A')
				else:  #20,1,45,8 20,5,32,8
					print ("--- MF sense get ---")
					if EMULATE_AF4518:
						bsend(b'0')
						continue					
					lsend(b'\x40F\xBA', 19)
					t=lrecv(b'\x40F\xBA', timeout=1)
					bsend(b'%d' % t[3])
			elif cmd1==b'\x21':
				if len(s)>0:  #20,16,32,23  20,17,32,23
					print ("!!! Zoom Pos Punt set -- not implemented !!!")
					bsend(b'F')
				else:    #
					print ("!!! Zoom punt get -- not implemented !!!") 
					bsend(b'0')
			else:
				print ("!!! F unknown %02x !!!" % cmd1[0])
			vd_sync=False
	
		elif cmd==b'B':
			cmd1=s[0:1]
			s=s[1:]			
			if cmd1==b'\x0B':  #20,13,32,66,F2
				print ("--- firmware reset ---")
				if (not FIXFW) and (EMULATE_AF4518 or DONT_TOUCH_FW):
					bsend(b'\x0B\x04')
					continue					
				lsendB(cmd1, s) 
				bsend(b'\x0B\x04')
			elif cmd1==b'\x0A':  #20,13,32,68,F3
				print ("--- firmware update prepare ---")
				if (not FIXFW) and (EMULATE_AF4518 or DONT_TOUCH_FW):
					bsend(b'\x0A\x04')
					continue					
				lsendB(cmd1, s) 
				bsend(b'\x0A\x04')
			elif cmd1==b'\x01':  #20,13,32,70,F4  a F0..40 'B' 01 ..55  get bootloader version
				print ("--- bootloader version get ---")
				if (not FIXFW) and (EMULATE_AF4518 or DONT_TOUCH_FW):
					bsend(b'\x10\x00\x10\x02\x04')
					continue					
				lsendB(cmd1, s) 
				s=lrecv(b'\x40X\x01')
				bsend(b'\x10\x00\x10'+s[3:4]+b'\x04')
			elif cmd1==b'\x02':  #20,13,33,64,F5  a F0..40..55
				print ("--- firmware flash cleaning ---")
				if SKIP_FLASH_CLEAN or (not FIXFW) and (EMULATE_AF4518 or DONT_TOUCH_FW):
					bsend(b'\x02\x04')
					continue	
				lsendB(cmd1, s)
				s=lrecv(b'\x40X\x02')
				bsend(b'\x02\x04')
			elif cmd1==b'\x03':  #20,13,34,64,F6  a F0..15..55 with firmware data
				print ("--- firmware hex data downloading ---")
				if (not FIXFW) and (EMULATE_AF4518 or DONT_TOUCH_FW):
					bsend(b'\x03\x04')
					continue
				lsendB(cmd1, s)
				s=lrecv(b'\x15')
				bsend(b'\x03\x04')
			elif cmd1==b'\x05':  #20,13,35,64,F7  a F0..40..55
				print ("--- exit bootloader ---")
				if (not FIXFW) and (EMULATE_AF4518 or DONT_TOUCH_FW):
					bsend(b'\x05\x04')
					continue	
				lsendB(cmd1, s) 
				bsend(b'\x05\x04')
			else:
				print ("!!! B unknown %02x !!!" % cmd1[0])
				
		elif cmd==b'P':
			if len(s)==0:  #20,15,32,21
				print ("--- custom mode get ---") 
				if EMULATE_AF4518:
					bsend(b'\x00\x00\x00\x00\x00\x00\x00\x01')
					continue					
				lsend(b'\x40P\xFA')
				s=lrecv(b'\x40P\xFA', timeout=1)
				bsend(t[3:11])
			else:
				cmd1=s[0:1]
				s=s[1:]
				if  cmd1==b'8':  #20,18,32,22
					print ("--- custom mode set ---")
					if EMULATE_AF4518:
						bsend(b'A')
						continue					
					lsend(b'\x40P\x38'+struct.pack('B', int(s[1:])+0x30), 19)
					t=lrecv(b'\x40F\x38', timeout=1)
					bsend(b'A')
				else:
					print ("!!! P unknown %02x !!!" % cmd1[0])
					bsend(b'F')
								
		elif cmd==b'I':
			cmd1=s[0:1]
			s=s[1:]
			if cmd1==b' ': #20,8,32,10
				print ("!!! IRIS offset reset -- not implemented !!!")
				bsend(b'F')
			elif cmd1==b'!': #20,10,32,11
				print ("!!! IRIS offset +1 -- not implemented !!!")
				bsend(b'F')
			elif cmd1==b'"': #20,11,32,12
				print ("!!! IRIS offset -1 -- not implemented !!!")
				bsend(b'F')
			elif cmd1==b'#': #20,9,32,13
				print ("!!! IRIS offset save to user config -- not implemented !!!")
				bsend(b'F')
			elif cmd1==b'$':   # 20,1,43,14  #20,7,34,14
				print ("!!! IRIS offset get -- not implemented !!!")
				bsend(b'0')
			elif cmd1==b'2':   # 20,7,32,16
				print ("!!! IRIS offset get -- not implemented !!!")
				bsend(b'0')
			else:
				print ("!!! I unknown %02x !!!" % cmd1[0])
				bsend(b'F')
				
		else:
			print ("!!! Cmd unknown %02x !!!" % cmd[0])
			bsend(b'F')

if __name__ == '__main__':
	try:
		#open serial port
		ser_broker=serial.Serial(
			port=PORT_BROKER,
	    	baudrate=115200,
			bytesize=serial.EIGHTBITS,
			parity=serial.PARITY_NONE,
			stopbits=serial.STOPBITS_ONE
		)

		if FIXFW or not EMULATE_AF4518:
			ser_lens=serial.Serial(
				port=PORT_LENS,
		    	baudrate=750000,
				bytesize=serial.EIGHTBITS,
				parity=serial.PARITY_NONE,
				stopbits=serial.STOPBITS_ONE
			)
			time.sleep(0.5)
			#send a start sequence to RTS
			ser_lens.rts=1
			time.sleep(0.1)
			ser_lens.rts=0
			time.sleep(0.1)
			ser_lens.rts=1
			ser_lens.dtr=0
	except Exception as e:
		print("failed to open serial ports：",e)
		exit(1)
  
   #make thread
	thr_b2l2b=threading.Thread(target=b2l2b, daemon=True)
	thr_vd=threading.Thread(target=vd, daemon=True)
	thr_b2l2b.start()
	thr_vd.start()
	
	#waitr for CTRL-C
	print ("Press CTRL-C to quit.")
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt as e:
		pass

	sys.exit(0)

