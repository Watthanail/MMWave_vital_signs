import socket
from enum import Enum
import numpy as np
import struct
import time
import csv
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
ADC_PARAMS = {'chirps': 8,  # 32
              'rx': 4,
              'tx': 2,
              'samples': 64,
              'IQ': 2,
              'bytes': 2}

MAX_PACKET_SIZE = 4096
BYTES_IN_PACKET = 1456

BYTES_IN_FRAME = (
    ADC_PARAMS['chirps'] * ADC_PARAMS['rx'] * ADC_PARAMS['tx'] *
    ADC_PARAMS['IQ'] * ADC_PARAMS['samples'] * ADC_PARAMS['bytes']
)
#BYTES_IN_FRAME_CLIPPED = (BYTES_IN_FRAME // BYTES_IN_PACKET) * BYTES_IN_PACKET
PACKETS_IN_FRAME = BYTES_IN_FRAME / BYTES_IN_PACKET

# ---------------------------------------------------
PACKETS_IN_FRAME_CLIPPED = BYTES_IN_FRAME // BYTES_IN_PACKET
PACKETS_IN_FRAME_FRACTION = BYTES_IN_FRAME % BYTES_IN_PACKET


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
        self.size_frame = None
        self.packet_number = None

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

        self.data_socket.settimeout(timeout)
        ret_frame = bytearray(BYTES_IN_FRAME)
        next_frame = bytearray(BYTES_IN_FRAME)
        packets_read = 1 
        
    
        while True:
            data, addr = self.data_socket.recvfrom(MAX_PACKET_SIZE)
            packet_num = struct.unpack('<1l', data[:4])[0]
            packet_data = data[10:]
            self.packet_number = packet_num

            # return packet_data,packet_num

            curr_idx = ((packet_num - 1)) % PACKETS_IN_FRAME_CLIPPED
            curr_array01 = curr_idx * BYTES_IN_PACKET
            curr_array02 = curr_array01 + len(packet_data)
            

            if curr_array02 <= BYTES_IN_FRAME:
                ret_frame[curr_array01:curr_array02] = packet_data
            else:
                overlap = curr_array02 - BYTES_IN_FRAME
                ret_frame[curr_array01:BYTES_IN_FRAME] = packet_data[:BYTES_IN_PACKET - overlap]
                next_frame[0:overlap] = packet_data[BYTES_IN_PACKET - overlap:]
            
            packets_read +=1

            if packets_read == PACKETS_IN_FRAME_CLIPPED:
                
                
                completed_frame = ret_frame
                ret_frame = next_frame
                next_frame = bytearray(BYTES_IN_FRAME)
                packets_read = 1
                # self.size_frame=len(completed_frame)

                # convert frame to int
                completed_frame = np.frombuffer(completed_frame, dtype=np.int16)

                return completed_frame
            

    def organize(self,raw_frame, num_chirps, num_rx, num_samples):
        ret = np.zeros(len(raw_frame) // 2, dtype=complex)
        ret[0::2] = raw_frame[0::4] + 1j * raw_frame[2::4]
        ret[1::2] = raw_frame[1::4] + 1j * raw_frame[3::4]
        return ret.reshape((num_chirps, num_rx, num_samples))


    def save_to_csv(self,filename,data):
        with open(filename,'w',newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Real','Imagine'])
            for row in data :
                writer.writerow([row.real,row.imag])

    def separate_tx(self,signal, num_tx, vx_axis=1, axis=0):
        """Separate interleaved radar data from separate TX along a certain axis to account for TDM radars."""
        reordering = np.arange(len(signal.shape))
        reordering[0] = axis
        reordering[axis] = 0
        signal = signal.transpose(reordering)
        out = np.concatenate([signal[i::num_tx, ...] for i in range(num_tx)], axis=vx_axis)
        return out.transpose(reordering)


if __name__== "__main__":

    dca = DCA1000(static_ip='192.168.33.30', adc_ip='192.168.33.180', data_port=4098, config_port=4096)
    dca.configure()
    start_time = time.time()
    complex_frames=[]

    # while time.time() - start_time <= 8:
    #     adc_data = dca.read(0.1)
    #     frame = dca.organize(adc_data, 8, 8,64) # TX*RX
    #     complex_frames.append(frame.flatten())


    # print(f"Completed Packet {adc_data}")
    # response = dca.send_command(CMD.RECORD_STOP_CMD_CODE)
    
    # dca.close()


#-------------------------------------------------------------------------------- 
    # with open('180824python_bufferframeadc04.bin', 'ab') as file:
    #     while time.time() - start_time <= 8:
    #         adc_data=dca.read(0.1)
    #         # frame = dca.organize(adc_data, 8, 8,64) # TX*RX
    #         file.write(adc_data)

#-------------------------------------------------------------------------------- 


    with open('180824python_organizeadc03.bin', 'ab') as file:
        while time.time() - start_time <= 8:
            adc_data=dca.read(0.1)
            frame = dca.organize(adc_data, 8, 8,64) # TX*RX
            file.write(adc_data)
            complex_frames.append(frame)

#-------------------------------------------------------------------------------- 


    response = dca.send_command(CMD.RECORD_STOP_CMD_CODE)
    all_complex_data = np.concatenate(complex_frames)
    # all_complex_data = np.concatenate(complex_frames, axis=0)
    dca.save_to_csv('180824python_organizeadc03.csv', all_complex_data)
    np.save('180824python_organizeadc03.npy', all_complex_data)

    # Separate the TX antennas
    num_tx = 2  # Set the number of transmit antennas
    separated_data = dca.separate_tx(all_complex_data, num_tx=num_tx, vx_axis=1, axis=0)
    # with open('180824python_Separateadc02.csv', 'w') as file:
    #     np.savetxt(file, separated_data.view(float).reshape(-1, 2), delimiter=',', fmt='%f')
    np.save('180824python_separatedadc03.npy', separated_data)

    
    print(f'Packnum : {dca.packet_number}')
    dca.close()

 