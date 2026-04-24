import socket
import time
import struct
import logging
import os

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("RakNet")

class RakNetProtocol:
    MAGIC = bytes.fromhex("00ffff00fefefefefdfdfdfd12345678")
    PROTOCOL_VERSION = 7
    MTU_SIZE = 1464

    # Packet IDs
    ID_CONNECTED_PING = 0x00
    ID_UNCONNECTED_PING = 0x01
    ID_UNCONNECTED_PING_OPEN_CONNECTIONS = 0x02
    ID_OPEN_CONNECTION_REQUEST_1 = 0x05
    ID_OPEN_CONNECTION_REPLY_1 = 0x06
    ID_OPEN_CONNECTION_REQUEST_2 = 0x07
    ID_OPEN_CONNECTION_REPLY_2 = 0x08
    ID_CONNECTION_REQUEST = 0x09
    ID_CONNECTION_REQUEST_ACCEPTED = 0x10
    ID_NEW_INCOMING_CONNECTION = 0x13
    
    # Custom Minebot bypass (if any)
    ID_CUSTOM_DIRECT_BYPASS = 0x00

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)
        self.client_guid = 1234567890123456 # Random 8-byte GUID
        self.state = 1
        self.last_send_time = 0

    def send_packet(self, packet):
        logger.debug(f"[RAW] Sending packet ID: 0x{packet[0]:x}, size: {len(packet)} to {self.host}:{self.port}")
        self.sock.sendto(packet, (self.host, self.port))

    def ping(self):
        # 1 byte ID + 8 bytes time + 16 bytes magic
        logger.info("Sending Unconnected Ping...")
        now = int(time.time() * 1000)
        packet = struct.pack(">BQ", self.ID_UNCONNECTED_PING, now) + self.MAGIC
        self.send_packet(packet)

    def broadcast_ping(self):
        logger.info("Broadcasting Unconnected Ping to find servers...")
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        now = int(time.time() * 1000)
        packet = struct.pack(">BQ", self.ID_UNCONNECTED_PING, now) + self.MAGIC
        self.sock.sendto(packet, ("255.255.255.255", 19132))

    def request_1(self):
        logger.info("Sending Open Connection Request 1...")
        # 1 byte ID + 16 bytes magic + 1 byte protocol version + padding
        packet = struct.pack(">B", self.ID_OPEN_CONNECTION_REQUEST_1) + self.MAGIC + struct.pack(">B", self.PROTOCOL_VERSION)
        padding_len = self.MTU_SIZE - len(packet)
        packet += b"\x00" * padding_len
        self.send_packet(packet)
        self.state = 3
        self.last_send_time = time.time()

    def request_2(self, server_guid, mtu):
        logger.info(f"Sending Open Connection Request 2 (MTU: {mtu})...")
        # 1 byte ID + 16 bytes magic + Server Address + MTU + Client GUID
        server_ip_parts = [int(x) for x in self.host.split('.')]
        address_bytes = struct.pack(">BBBBBH", 4, server_ip_parts[0], server_ip_parts[1], server_ip_parts[2], server_ip_parts[3], self.port)
        packet = struct.pack(">B16s", self.ID_OPEN_CONNECTION_REQUEST_2, self.MAGIC) + address_bytes + struct.pack(">HQB", mtu, self.client_guid, 0)
        self.send_packet(packet)
        self.state = 4
        self.last_send_time = time.time()
        self.server_guid = server_guid
        self.mtu = mtu

    def handle_reply_1(self, packet):
        logger.info("Received Open Connection Reply 1!")
        # 1 byte ID + 16 bytes magic + 8 bytes server GUID + 1 byte security + 2 bytes MTU
        if len(packet) >= 28:
            server_guid, security, mtu = struct.unpack(">QBH", packet[17:28])
            logger.debug(f"Server GUID: {server_guid}, MTU: {mtu}")
            self.request_2(server_guid, mtu)

    def handle_reply_2(self, packet):
        logger.info("Received Open Connection Reply 2!")
        self.state = 5
        self.send_connection_request()

    def send_encapsulated(self, payload, reliable=True):
        if not hasattr(self, 'seq_num'):
            self.seq_num = 0
            
        flags = 0x40 if reliable else 0x00
        bit_len = len(payload) * 8
        encap = struct.pack(">BH", flags, bit_len)
        
        if reliable:
            if not hasattr(self, 'rel_num'):
                self.rel_num = 0
            encap += struct.pack("<I", self.rel_num)[:3]
            self.rel_num += 1
            
        encap += payload
        
        data_packet = struct.pack(">B", 0x84)
        data_packet += struct.pack("<I", self.seq_num)[:3]
        data_packet += encap
        
        self.send_packet(data_packet)
        self.seq_num += 1

    def send_connection_request(self):
        logger.info("Sending Encapsulated Connection Request (0x09)...")
        now = int(time.time() * 1000)
        payload = struct.pack(">BQQB", 0x09, self.client_guid, now, 0)
        self.send_encapsulated(payload)

    def handle_data_packet(self, packet):
        # Very simplified parsing for Data Packets
        if len(packet) < 4: return
        seq_num = struct.unpack("<I", packet[1:4] + b"\x00")[0]
        
        # Ack it
        ack = struct.pack(">BH", 0xc0, 1) + struct.pack("<I", seq_num)[:3] + struct.pack("<I", seq_num)[:3]
        self.send_packet(ack)
        
        offset = 4
        while offset < len(packet):
            flags = packet[offset]
            reliability = (flags & 0xe0) >> 5
            split = (flags & 0x10) > 0
            
            bit_len = struct.unpack(">H", packet[offset+1:offset+3])[0]
            byte_len = (bit_len + 7) // 8
            offset += 3
            
            if reliability in (2, 3, 4):  # reliable
                offset += 3
            if reliability == 1 or reliability == 4: # sequenced
                offset += 3
            if reliability == 3 or reliability == 4: # ordered
                offset += 4
            if split:
                offset += 10
                
            payload = packet[offset:offset+byte_len]
            offset += byte_len
            
            if len(payload) > 0:
                self.handle_encapsulated(payload)

    def handle_encapsulated(self, payload):
        pid = payload[0]
        if pid == 0x10:
            logger.info("Received Connection Request Accepted (0x10)!")
            self.send_new_incoming_connection()
        elif pid == 0x13:
            pass # We don't care
        elif pid == 0x00:
            ping_time = payload[1:9]
            pong = struct.pack(">B", 0x03) + ping_time + struct.pack(">Q", int(time.time() * 1000))
            self.send_encapsulated(pong)
        else:
            logger.debug(f"Received Encapsulated Packet ID: 0x{pid:x}")

    def send_new_incoming_connection(self):
        logger.info("Sending New Incoming Connection (0x13)...")
        now = int(time.time() * 1000)
        
        # 1 byte ID + Server Address + 10 Internal Addresses + 16 bytes ping time
        server_ip_parts = [int(x) for x in self.host.split('.')]
        sys_addr = struct.pack(">BBBBBH", 4, server_ip_parts[0], server_ip_parts[1], server_ip_parts[2], server_ip_parts[3], self.port)
        
        internal_addr = struct.pack(">BBBBBH", 4, 127, 0, 0, 1, self.port)
        payload = struct.pack(">B", 0x13) + sys_addr + (internal_addr * 10) + struct.pack(">QQ", now, now)
        self.send_encapsulated(payload)
        
        self.state = 6
        self.send_login_blob()

    def send_login_blob(self):
        blob_path = os.path.join(os.path.dirname(__file__), "login_blob.bin")
        if not os.path.exists(blob_path):
            logger.error("login_blob.bin not found! Cannot join game.")
            return

        with open(blob_path, "rb") as f:
            blob = f.read()

        chunk_size = 1432
        split_count = (len(blob) + chunk_size - 1) // chunk_size
        split_id = 1234  # Random ID

        logger.info(f"Splitting 16KB Login Blob into {split_count} packets...")
        
        # We need a sequence number for data packets
        if not hasattr(self, 'seq_num'):
            self.seq_num = 0
            
        for i in range(split_count):
            chunk = blob[i * chunk_size : (i + 1) * chunk_size]
            
            # RakNet Encapsulated Packet (Reliable + Split = 0x50)
            flags = 0x50
            bit_len = len(chunk) * 8
            
            encap = struct.pack(">BH", flags, bit_len)
            
            # Reliable Message Number (3 bytes LE) - Dummy value for now
            encap += struct.pack("<I", self.seq_num)[:3]
            
            # Split Count (4), Split ID (2), Split Index (4)
            encap += struct.pack(">IHI", split_count, split_id, i)
            
            encap += chunk
            
            # Wrap in Data Packet 0x84
            data_packet = struct.pack(">B", 0x84)
            data_packet += struct.pack("<I", self.seq_num)[:3]  # Sequence number
            data_packet += encap
            
            self.send_packet(data_packet)
            self.seq_num += 1
            time.sleep(0.01)

    def update(self):
        now = time.time()
        if self.state == 1:
            self.request_1()
        elif self.state == 3 and now - self.last_send_time > 2.0:
            logger.warning("Timeout waiting for Reply 1. Resending Request 1...")
            self.request_1()
        elif self.state == 4 and now - self.last_send_time > 2.0:
            logger.warning("Timeout waiting for Reply 2. Resending Request 2...")
            self.request_2(self.server_guid, self.mtu)

        try:
            data, addr = self.sock.recvfrom(2048)
            packet_id = data[0]
            logger.debug(f"Received Packet ID: 0x{packet_id:x}, size: {len(data)}")
            
            if packet_id == 0x1C:
                logger.info(f"Received Unconnected Pong from {addr}!")
                # ID (1) + Time (8) + Server GUID (8) + Magic (16) + Server Name string
                if len(data) > 33:
                    server_name = data[33:].decode('utf-8', errors='ignore')
                    logger.info(f"Server Name: {server_name}")
                    if (self.host != addr[0] or self.port != addr[1]) and self.state == 1:
                        logger.info(f"Updating target host to {addr[0]}:{addr[1]}")
                        self.host = addr[0]
                        self.port = addr[1]
            elif packet_id == self.ID_OPEN_CONNECTION_REPLY_1 and self.state == 3:
                self.handle_reply_1(data)
            elif packet_id == self.ID_OPEN_CONNECTION_REPLY_2 and self.state == 4:
                self.handle_reply_2(data)
            elif packet_id >= 0x80 and packet_id <= 0x8f:
                self.handle_data_packet(data)
            elif packet_id == 0xc0:
                pass # Ignore ACKs for now
            elif packet_id == self.ID_UNCONNECTED_PING:
                logger.debug("Ignored broadcast unconnected ping")
            else:
                logger.debug(f"Unhandled packet ID: 0x{packet_id:x} in state {self.state}")
                
        except socket.timeout:
            pass
        except ConnectionResetError:
            logger.warning("Connection Reset by Peer (WinError 10054). Is the server offline or blocking localhost UDP?")
            # Windows sends ICMP unreachable when UDP port is closed or blocked.
            time.sleep(1)

    def run(self):
        logger.info(f"Looking for server on port {self.port} (0.14.0 Mode)...")
        self.broadcast_ping()
        self.ping()
        while True:
            self.update()
            time.sleep(0.05)
