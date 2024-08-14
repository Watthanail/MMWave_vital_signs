
import time
import codecs
import socket
import struct
from enum import Enum

import numpy as np


class CMD(Enum):
    RESET_FPGA_CMD_CODE = '0100'
    RESET_AR_DEV_CMD_CODE = '0200'
    CONFIG_FPGA_GEN_CMD_CODE = '0300'
    CONFIG_EEPROM_CMD_CODE = '0400'
    RECORD_START_CMD_CODE = '0500'
    RECORD_STOP_CMD_CODE = '0600'
    PLAYBACK_START_CMD_CODE = '0700'
    PLAYBACK_STOP_CMD_CODE = '0800'
    SYSTEM_CONNECT_CMD_CODE = '0900'
    SYSTEM_ERROR_CMD_CODE = '0a00'
    CONFIG_PACKET_DATA_CMD_CODE = '0b00'
    CONFIG_DATA_MODE_AR_DEV_CMD_CODE = '0c00'
    INIT_FPGA_PLAYBACK_CMD_CODE = '0d00'
    READ_FPGA_VERSION_CMD_CODE = '0e00'

    def __str__(self):
        return str(self.value)


# MESSAGE = codecs.decode(b'5aa509000000aaee', 'hex')
CONFIG_HEADER = '5aa5'
CONFIG_STATUS = '0000'
CONFIG_FOOTER = 'aaee'
ADC_PARAMS = {'chirps': 8,  # 32
              'rx': 4,
              'tx': 2,
              'samples': 64,
              'IQ': 2,
              'bytes': 2}
# STATIC
MAX_PACKET_SIZE = 4096
BYTES_IN_PACKET = 1024#1456
# DYNAMIC
BYTES_IN_FRAME = (ADC_PARAMS['chirps'] * ADC_PARAMS['rx'] * ADC_PARAMS['tx'] *
                  ADC_PARAMS['IQ'] * ADC_PARAMS['samples'] * ADC_PARAMS['bytes']) #16384


#BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME // BYTES_IN_PACKET) * BYTES_IN_PACKET
# PACKETS_IN_FRAME = BYTES_IN_FRAME / BYTES_IN_PACKET
PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME // BYTES_IN_PACKET #11
BYTES_IN_FRAME_CLIPPED = PACKETS_IN_FRAME_CLIPPED * BYTES_IN_PACKET #16016
UINT16_IN_PACKET = BYTES_IN_PACKET // 2
UINT16_IN_FRAME = BYTES_IN_FRAME // 2


class DCA1000:
    """Software interface to the DCA1000 EVM board via ethernet.

    Attributes:
        static_ip (str): IP to receive data from the FPGA
        adc_ip (str): IP to send configuration commands to the FPGA
        data_port (int): Port that the FPGA is using to send data
        config_port (int): Port that the FPGA is using to read configuration commands from


    General steps are as follows:
        1. Power cycle DCA1000 and XWR1xxx sensor
        2. Open mmWaveStudio and setup normally until tab SensorConfig or use lua script
        3. Make sure to connect mmWaveStudio to the board via ethernet
        4. Start streaming data
        5. Read in frames using class

    Examples:
        >>> dca = DCA1000()
        >>> adc_data = dca.read(timeout=.1)
        >>> frame = dca.organize(adc_data, 128, 4, 256)

    """

    def __init__(self, static_ip='192.168.33.30', adc_ip='192.168.33.180',
                 data_port=4098, config_port=4096):
        # Save network data
        # self.static_ip = static_ip
        # self.adc_ip = adc_ip
        # self.data_port = data_port
        # self.config_port = config_port

        # Create configuration and data destinations
        self.cfg_dest = (adc_ip, config_port)
        self.cfg_recv = (static_ip, config_port)
        self.data_recv = (static_ip, data_port)

        # Create sockets
        self.config_socket = socket.socket(socket.AF_INET,
                                           socket.SOCK_DGRAM,
                                           socket.IPPROTO_UDP)
        self.data_socket = socket.socket(socket.AF_INET,
                                         socket.SOCK_DGRAM,
                                         socket.IPPROTO_UDP)

        # Bind data socket to fpga
        self.data_socket.bind(self.data_recv)

        # Bind config socket to fpga
        self.config_socket.bind(self.cfg_recv)

        self.data = []
        self.packet_count = []
        self.packet_fail=0
        self.byte_count = []

        self.frame_buff = []

        self.curr_buff = None
        self.last_frame = None


        self.lost_packets_during_read = []
        self.number_lost_packets=[]
        self.lost_bytecount =[]
        self.start_bytecount=[]
        self.start_packetnum=[]
        

        self.lost_packets_number=[]
        self.previous_packet_number= None
        
        self.notmath_packets=[]
        

    def configure(self):
        """Initializes and connects to the FPGA

        Returns:
            None

        """
        # SYSTEM_CONNECT_CMD_CODE
        # 5a a5 09 00 00 00 aa ee
        print(self._send_command(CMD.SYSTEM_CONNECT_CMD_CODE))

        # READ_FPGA_VERSION_CMD_CODE
        # 5a a5 0e 00 00 00 aa ee
        print(self._send_command(CMD.READ_FPGA_VERSION_CMD_CODE))

        # CONFIG_FPGA_GEN_CMD_CODE

        # 5a a5 03 00 06 00 01 02 01 02 03 1e aa ee
        print(self._send_command(CMD.CONFIG_FPGA_GEN_CMD_CODE, '0600', '01020102031e'))
                                                                        
        # CONFIG_PACKET_DATA_CMD_CODE  Configure record dela
        # 5a a5 0b 00 06 00 c0 05 35 0c 00 00 aa ee
        print(self._send_command(CMD.CONFIG_PACKET_DATA_CMD_CODE, '0600', 'be05350c0000'))


      
        # 5a a5 05 00 00 00 aa ee
        print(self._send_command(CMD.RECORD_START_CMD_CODE))

    def close(self):
        """Closes the sockets that are used for receiving and sending data

        Returns:
            None

        """
        self.data_socket.close()
        self.config_socket.close()

    def read(self, timeout=1):
        """ Read in a single packet via UDP

        Args:
            timeout (float): Time to wait for packet before moving on

        Returns:
            Full frame as array if successful, else None

        """
        
        # Configure
        self.data_socket.settimeout(timeout)
        print("-----Start-----------")
        # Frame buffer
        ret_frame = np.zeros(UINT16_IN_FRAME, dtype=np.uint16)

        # Wait for start of next frame
        while True:
            try:
                packet_num, byte_count, packet_data = self._read_data_packet()
                # if packet_num - self.previous_packet_number > 1  :
                #     self.lost_packets_number.append(packet_num)
                #     self.previous_packet_number = packet_num  

                if byte_count % BYTES_IN_FRAME_CLIPPED == 0:
                #if byte_count % BYTES_IN_FRAME == 0:
                    packets_read = 1
                    # print(f"Packet read:{packets_read}")
                    ret_frame[0:UINT16_IN_PACKET] = packet_data
                    self.start_packetnum.append(packet_num)
                    self.start_bytecount.append(byte_count)
                    # self.previous_packet_number = packet_num

                    break
            except :
                pass
                # self.packet_fail += 1
                # print(f"Packet read failed_1:{self.packet_fail}")

        # Read in the rest of the frame            
        while True:
            try:
                packet_num, byte_count, packet_data = self._read_data_packet()
                packets_read += 1
               
                
                # if packet_num - self.previous_packet_number > 0 :
                #     self.lost_packets_number.append(packet_num)
                #     self.previous_packet_number = packet_num                
                    
                if byte_count % BYTES_IN_FRAME_CLIPPED == 0:
                # if byte_count % BYTES_IN_FRAME == 0:
                    self.lost_packets_during_read.append(PACKETS_IN_FRAME_CLIPPED - packets_read)
                    self.lost_bytecount.append(byte_count)
                    # self.previous_packet_number = packet_num
                    return ret_frame

                curr_idx = ((packet_num - 1) % PACKETS_IN_FRAME_CLIPPED)
                # self.previous_packet_number = packet_num
                try:
                    ret_frame[curr_idx * UINT16_IN_PACKET:(curr_idx + 1) * UINT16_IN_PACKET] = packet_data
                    # self.previous_packet_number = packet_num
                except :
                    pass
                    #self.packet_fail +=1
                    #print(f"Packet read failed_2:{self.packet_fail}")


                if packets_read > PACKETS_IN_FRAME_CLIPPED:
                    # self.previous_packet_number = packet_num 
                    packets_read = 0
            except :
                pass


        



    def _send_command(self, cmd, length='0000', body='', timeout=1):
        """Helper function to send a single commmand to the FPGA

        Args:
            cmd (CMD): Command code to send to the FPGA
            length (str): Length of the body of the command (if any)
            body (str): Body information of the command
            timeout (int): Time in seconds to wait for socket data until timeout

        Returns:
            str: Response message

        """
        # Create timeout exception
        self.config_socket.settimeout(timeout)

        # Create and send message
        resp = ''
        msg = codecs.decode(''.join((CONFIG_HEADER, str(cmd), length, body, CONFIG_FOOTER)), 'hex')
        try:
            self.config_socket.sendto(msg, self.cfg_dest)
            resp, addr = self.config_socket.recvfrom(MAX_PACKET_SIZE)
        except socket.timeout as e:
            print(e)
        return resp

    def _read_data_packet(self):
        """Helper function to read in a single ADC packet via UDP

        Returns:
            int: Current packet number, byte count of data that has already been read, raw ADC data in current packet

        """
        data, addr = self.data_socket.recvfrom(MAX_PACKET_SIZE)
        # print(f"Raw UDP packet data: {len(data)}", data.hex())
        packet_num = struct.unpack('<1l', data[:4])[0]
        byte_count = struct.unpack('>Q', b'\x00\x00' + data[4:10][::-1])[0]
        packet_data = np.frombuffer(data[10:], dtype=np.int16)
#
        # print("Raw UDP packet data:", data.hex())
        #print(f"Length of received data packet: {len(data)} bytes : {packet_num} Byte count: {byte_count} Packet data: {len(packet_data)}")
        # print("Packet number :", packet_num)
        # print("Byte count:", byte_count)
        # print("Packet data (uint16 array):", packet_data)
        return packet_num, byte_count, packet_data

    def _listen_for_error(self):
        """Helper function to try and read in for an error message from the FPGA

        Returns:
            None

        """
        self.config_socket.settimeout(None)
        msg = self.config_socket.recvfrom(MAX_PACKET_SIZE)
        if msg == b'5aa50a000300aaee':
            print('stopped:', msg)

    def _stop_stream(self):
        """Helper function to send the stop command to the FPGA

        Returns:
            str: Response Message

        """
        return self._send_command(CMD.RECORD_STOP_CMD_CODE)

    @staticmethod
    def organize(raw_frame, num_chirps, num_rx, num_samples):
        """Reorganizes raw ADC data into a full frame

        Args:
            raw_frame (ndarray): Data to format
            num_chirps: Number of chirps included in the frame
            num_rx: Number of receivers used in the frame
            num_samples: Number of ADC samples included in each chirp

        Returns:
            ndarray: Reformatted frame of raw data of shape (num_chirps, num_rx, num_samples)

        """
        ret = np.zeros(len(raw_frame) // 2, dtype=complex)

        # Separate IQ data
        ret[0::2] = raw_frame[0::4] + 1j * raw_frame[2::4]
        ret[1::2] = raw_frame[1::4] + 1j * raw_frame[3::4]
        # print(f"LVDS lan {ret.size} : {ret}")
        return ret.reshape((num_chirps, num_rx, num_samples))

if __name__ == "__main__":
    dca = DCA1000(static_ip='192.168.33.30', adc_ip='192.168.33.180', data_port=4098, config_port=4096)
    
    # Run the configure method
    dca.configure()

    # Start time
    start_time = time.time()

    # Read data for 10 seconds
    # while time.time() - start_time <= 8.00175:
    while time.time() - start_time <= 8:
        adc_data = dca.read(0.1)

        # if adc_data is not None:
        #     print("Frame data received successfully.")
            # print("Raw frame data:", adc_data)
            
            # print(frame)

        
            
            #print("Raw  data:", adc_data)
        # frame = dca.organize(adc_data, ADC_PARAMS['chirps'], 8,ADC_PARAMS['samples']) # TX*RX
        # print("rame:", frame)
            # hex_frame_data = [hex(x) for x in frame_data]
            # print(f"Hex frame {frame_count} data: {hex_frame_data}")
            # hex_frame_data = [f"{x:04x}" for x in frame_data]
            
            # formatted_hex_data=[]
            # for i in range(0,len(hex_frame_data),8):
            #     hex_line = ' '.join(hex_frame_data[i:i+8])
            #     formatted_hex_data.append(f"{i}  : {hex_line}")

            # for line in formatted_hex_data:
            #     print(line)

            

        # else:
        #     print("Failed to receive frame data.")

    # Stop recording
    print(f"Raw  data length: {len(adc_data)}")    
    response = dca._send_command(CMD.RECORD_STOP_CMD_CODE)
    print(f"Response for RECORD_STOP_CMD_CODE: {response.hex() if isinstance(response, bytes) else response}")
    # print(f"Packet fails: {dca.packet_fail} : {dca.lost_packets}")
    # print(f"PACKETS_IN_FRAME_CLIPPED: {PACKETS_IN_FRAME_CLIPPED}")
    # print(f"Total_FRAME: {dca.num_frame1 ,dca.num_frame2 }")
    print("--------------------------------------------------------")
    print(f"Start Packet number : {dca.start_packetnum} <=> {len(dca.start_packetnum)}")
    print(f"Start Packet bytecount : {dca.start_bytecount} <=> {len(dca.start_bytecount)}")
    print("--------------------------------------------------------")

    # print("*******Data lost************")
    # print(f"lost Packet number : {dca.lost_packets_number} <=> {len(dca.lost_packets_number)}")

    print("--------------------------------------------------------")
    print(f"lost Packet bytecount : {dca.lost_bytecount} <=> {len(dca.lost_bytecount)}")
    print(f"lost Packet number during read : {dca.lost_packets_during_read} <=> {len(dca.lost_packets_during_read)}")



    # Close the connection
    dca.close()