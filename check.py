import pyshark

def capture_udp_packets(interface, capture_duration):
    """Captures UDP packets on a specified network interface for a given duration.

    Args:
        interface (str): The network interface to capture packets on.
        capture_duration (int): Duration in seconds to capture packets.

    Returns:
        list: List of payload sizes of captured UDP packets.
    """
    capture = pyshark.LiveCapture(interface=interface, bpf_filter='udp')
    capture.sniff(timeout=capture_duration)

    udp_payload_sizes = []
    for packet in capture:
        try:
            # Get the UDP layer
            udp_layer = packet.udp
            # Calculate payload size by subtracting the UDP header size (8 bytes) from total length
            payload_size = int(udp_layer.length) - 8
            udp_payload_sizes.append(payload_size)
            print(f"Captured UDP packet with payload size: {payload_size} bytes")
        except AttributeError:
            # Skip packets that don't have UDP layer
            continue
    
    return udp_payload_sizes

if __name__ == "__main__":
    # Network interface to capture packets on (change this to your specific interface)
    interface = 'eth0'  # Example: 'eth0', 'wlan0', 'en0' for Mac, etc.
    capture_duration = 10  # Duration in seconds to capture packets

    # Capture UDP packets
    payload_sizes = capture_udp_packets(interface, capture_duration)

    # Determine max packet size and bytes in packet
    if payload_sizes:
        max_packet_size = max(payload_sizes) + 8  # Adding 8 bytes for UDP header
        bytes_in_packet = max(payload_sizes)
        print(f"Max packet size: {max_packet_size} bytes")
        print(f"Bytes in packet: {bytes_in_packet} bytes")
    else:
        print("No UDP packets captured.")
