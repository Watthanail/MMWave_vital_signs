import socket
from enum import Enum
import numpy as np
import struct
import time


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

CONFIG_HEADER = '5AA5'
CONFIG_FOOTER = 'AAEE'
CONFIG_STATUS = '0000'
ADC_PARAMS = {
    'chirps': 128,
    'rx': 4,
    'tx': 3,
    'samples': 128,
    'IQ': 2,
    'bytes': 2
}

MAX_PACKET_SIZE = 4096
BYTES_IN_PACKET = 1456

BYTES_IN_FRAME = (
    ADC_PARAMS['chirps'] * ADC_PARAMS['rx'] * ADC_PARAMS['tx'] *
    ADC_PARAMS['IQ'] * ADC_PARAMS['samples'] * ADC_PARAMS['bytes']
)
BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME // BYTES_IN_PACKET) * BYTES_IN_PACKET
PACKETS_IN_FRAME = BYTES_IN_FRAME / BYTES_IN_PACKET
PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME // BYTES_IN_PACKET
UINT16_IN_PACKET = BYTES_IN_PACKET // 2
UINT16_IN_FRAME = BYTES_IN_FRAME // 2

class DCA1000:
    """Software interface to the DCA1000 EVM board via ethernet."""

    def __init__(self, static_ip='192.168.33.30', adc_ip='192.168.33.180',
                 data_port=4098, config_port=4096, timeout=5.0):
        # Save network data
        self.static_ip = static_ip
        self.adc_ip = adc_ip
        self.data_port = data_port
        self.config_port = config_port
        self.timeout = timeout

        # Create configuration and data destinations
        self.cfg_dest = (self.adc_ip, self.config_port)
        self.cfg_recv = (self.static_ip, self.config_port)
        self.data_recv = (self.static_ip, self.data_port)

        # Create sockets
        self.config_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Bind sockets
        self.data_socket.bind(self.data_recv)
        self.config_socket.bind(self.cfg_recv)

        # Set socket timeout
        self.config_socket.settimeout(self.timeout)

        # Initialize instance variables
        self.data = []
        self.packet_count = []
        self.byte_count = []
        self.frame_buff = []
        self.curr_buff = None
        self.last_frame = None
        self.lost_packets = None

    def close(self):
        """Closes the sockets that are used for receiving and sending data"""
        self.data_socket.close()
        self.config_socket.close()

    def send_command(self, cmd, length='0000', params='', timeout=1):
        """Sends a command to the device and waits for a response."""
        self.config_socket.settimeout(timeout)
        if isinstance(cmd, CMD):
            header = CONFIG_HEADER
            status = CONFIG_STATUS
            footer = CONFIG_FOOTER
            command_code = cmd.value
            message = bytes.fromhex(header + command_code + length + params + footer)
        elif isinstance(cmd, str):
            message = bytes.fromhex(cmd)
        else:
            raise ValueError("Invalid command type. Expected CMD enum or string.")
        
        print("Message being sent:", message.hex())
        self.config_socket.sendto(message, self.cfg_dest)
        
        try:
            response, _ = self.config_socket.recvfrom(4096)
            return response
        except socket.timeout:
            return "Error: Command response timed out."

    def configure(self):
        """Initializes and connects to the FPGA"""
        # SYSTEM_CONNECT_CMD_CODE

        # 5a a5 09 00 00 00 aa ee
        print(self.send_command(CMD.SYSTEM_CONNECT_CMD_CODE).hex())


        # READ_FPGA_VERSION_CMD_CODE
        # 5a a5 0e 00 00 00 aa ee
        print(self.send_command(CMD.READ_FPGA_VERSION_CMD_CODE).hex())

        # CONFIG_FPGA_GEN_CMD_CODE
        # 5a a5 03 00 06 00 01 02 01 02 03 1e aa ee

        print(self.send_command(CMD.CONFIG_FPGA_GEN_CMD_CODE, '0600', '01020102031e').hex())

        # CONFIG_PACKET_DATA_CMD_CODE
        # 5a a5 0b 00 06 00 be 05 35 0c 00 00 aa ee                       

        print(self.send_command(CMD.CONFIG_PACKET_DATA_CMD_CODE, '0600', 'be05350c0000').hex())

        # RECORD_START_CMD_CODE
        print(self.send_command(CMD.RECORD_START_CMD_CODE).hex())
    def read(self, timeout=1):
        """ Read in a single packet via UDP

        Args:
            timeout (float): Time to wait for packet before moving on

        Returns:
            Full frame as array if successful, else None

        """
        # Configure
        self.data_socket.settimeout(timeout)

        # Frame buffer
        ret_frame = np.zeros(UINT16_IN_FRAME, dtype=np.uint16)

        # Wait for start of next frame
        while True:
            packet_num, byte_count, packet_data = self._read_data_packet()
            if packet_num is None or byte_count is None or packet_data is None:
                return None
            if byte_count % BYTES_IN_FRAME_CLIPPED == 0:
                packets_read = 1
                ret_frame[0:UINT16_IN_PACKET] = packet_data
                break

        # Read in the rest of the frame            
        while True:
            packet_num, byte_count, packet_data = self._read_data_packet()
            if packet_num is None or byte_count is None or packet_data is None:
                return None
            packets_read += 1

            if byte_count % BYTES_IN_FRAME_CLIPPED == 0:
                self.lost_packets = PACKETS_IN_FRAME_CLIPPED - packets_read
                return ret_frame

            curr_idx = ((packet_num - 1) % PACKETS_IN_FRAME_CLIPPED)
            try:
                ret_frame[curr_idx * UINT16_IN_PACKET:(curr_idx + 1) * UINT16_IN_PACKET] = packet_data
            except:
                pass

            if packets_read > PACKETS_IN_FRAME_CLIPPED:
                packets_read = 0

    def _read_data_packet(self):
        """Helper function to read in a single ADC packet via UDP

        Returns:
            int: Current packet number, byte count of data that has already been read, raw ADC data in current packet

        """
        # data, addr = self.data_socket.recvfrom(MAX_PACKET_SIZE)
        # packet_num = struct.unpack('<1l', data[:4])[0]
        # byte_count = struct.unpack('>Q', b'\x00\x00' + data[4:10][::-1])[0]
        # packet_data = np.frombuffer(data[10:], dtype=np.uint16)
        # print(f"Packet Number: {packet_num}, Byte Count: {byte_count}, Packet Data: {packet_data}")

        # return packet_num, byte_count, packet_data
        try:
            data, addr = self.data_socket.recvfrom(MAX_PACKET_SIZE)
            packet_num = struct.unpack('<1l', data[:4])[0]
            byte_count = struct.unpack('>Q', b'\x00\x00' + data[4:10][::-1])[0]
            packet_data = np.frombuffer(data[10:], dtype=np.uint16)
            print(f"Packet Number: {packet_num}, Byte Count: {byte_count}, Packet Data: {packet_data}")
            return packet_num, byte_count, packet_data
        except socket.timeout:
            print("Error: Data packet receive timed out.")
            return None, None, None
        except Exception as e:
            print(f"Error: {e}")
            return None, None, None
    
    def _listen_for_error(self):
        """Helper function to try and read in for an error message from the FPGA

        Returns:
            None

        """
        self.config_socket.settimeout(None)
        msg = self.config_socket.recvfrom(MAX_PACKET_SIZE)
        if msg == b'5aa50a000300aaee':
            print('stopped:', msg)

if __name__ == "__main__":
    dca = DCA1000(static_ip='192.168.33.30', adc_ip='192.168.33.180', data_port=4098, config_port=4096, timeout=5.0)
    
    #RECORD_STOP_CMD_CODE
    command_setup = '5aa506000000aaee'

    #RECORD_START_CMD_CODE
    #command_setup = '5aa505000000aaee'

    response_setup = dca.send_command(command_setup)
    # response_version = dca.send_command(CMD.READ_FPGA_VERSION_CMD_CODE)
    
    # if isinstance(response_setup, bytes):
    #     print("Response (custom command):", response_setup.hex())
    # else:
    #     print("Response (custom command):", response_setup)

    # if isinstance(response_version, bytes):
    #     print("Response (READ_FPGA_VERSION_CMD):", response_version.hex())
    # else:
    #     print("Response (READ_FPGA_VERSION_CMD):", response_version)

    # Run the configure method
    # dca.configure()

    #  Start time
    # start_time = time.time()
    
    # # Read data for 10 seconds
    # while time.time() - start_time < 20:
    #      print("ll")
        # frame_data = dca.read()
        # if frame_data is not None:
        #     print("Frame data received successfully.")
        # else:
        #     print("Failed to receive frame data.")
    
    # Close the connection
    dca.close()
