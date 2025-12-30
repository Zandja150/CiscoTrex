import sys
import os
import time

CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))
TREX_LIB_PATH = os.path.abspath(os.path.join(CURRENT_PATH, '../automation/trex_control_plane/interactive'))
if TREX_LIB_PATH not in sys.path:
    sys.path.insert(0, TREX_LIB_PATH)
from trex_stl_lib.api import *

# =========================================================================
#  CONFIGURATION (100Gbps UNIDIRECTIONAL)
# =========================================================================

# --- ROUTER MAC ADDRESSES ---
# Interface facing Sender (Port 1)
ROUTER_MAC_SENDER   = "00:32:17:75:a8:80"
# Interface facing Receiver (Port 0)
ROUTER_MAC_RECEIVER = "00:32:17:75:a8:84"

# --- IP ADDRESSES ---
TREX_IP_P0   = "12.12.12.2" # Receiver
ROUTER_IP_P0 = "12.12.12.1"

TREX_IP_P1   = "11.11.11.2" # Sender
ROUTER_IP_P1 = "11.11.11.1"

# --- TRAFFIC FLOW ---
SRC_IP = "16.0.0.1"
DST_IP = "48.0.0.1"
# =========================================================================

def main():
    c = STLClient()
    try:
        print("1. Connecting to TRex...")
        c.connect()
        c.acquire(ports=[0, 1], force=True)
        c.reset(ports=[0, 1])
        c.clear_stats()

        # Get Sender MAC
        port_info = c.get_port_info(ports=[0, 1])
        sender_mac = port_info[1]['hw_mac']

        print("2. Refreshing ARP (Ping Trick)...")
        c.set_service_mode(ports=[0, 1], enabled=True)
        
        # Configure IPs
        c.set_l3_mode(port=0, src_ipv4=TREX_IP_P0, dst_ipv4=ROUTER_IP_P0)
        c.set_l3_mode(port=1, src_ipv4=TREX_IP_P1, dst_ipv4=ROUTER_IP_P1)
        
        try:
            # Ping Router from Receiver Port (Port 0) so Router knows where to send the 100G
            c.ping_ip(src_port=0, dst_ip=ROUTER_IP_P0, pkt_size=64, count=5)
            # Ping Router from Sender Port (Port 1) just in case
            c.ping_ip(src_port=1, dst_ip=ROUTER_IP_P1, pkt_size=64, count=3)
            print("   ARP refreshed.")
        except STLError:
            pass 

        time.sleep(1)
        c.set_service_mode(ports=[0, 1], enabled=False)

        # --- STEP 3: TRAFFIC ---
        print("\n3. Starting 100Gbps Stream...")
        print(f"   Sender: Port 1 -> Router")
        print(f"   Target: Router -> Port 0")
        
        # 100G Packet
        pkt = STLPktBuilder(
            pkt = Ether(src=sender_mac, dst=ROUTER_MAC_SENDER) / 
                  IP(src=SRC_IP, dst=DST_IP) / 
                  UDP(dport=1234, sport=1234) /
                  ('x' * 1400)
        )
        
        s1 = STLStream(packet=pkt, mode=STLTXCont())
        c.add_streams(s1, ports=[1]) # Add ONLY to Sender Port

        # --- THE 100G PUSH ---
        try:
            # We use "100%" to force the card to max line rate (100Gbps)
            c.start(ports=[1], mult="100%", duration=300)
        except STLError as e:
            print(f"   [!] Error starting traffic: {e}")
            return
            
        c.wait_on_traffic(ports=[1])

        # --- STEP 4: RESULTS ---
        time.sleep(1)
        stats = c.get_stats()
        
        tx_packets = stats[1]['opackets'] # Sent from Port 1
        rx_packets = stats[0]['ipackets'] # Received on Port 0
        lost = tx_packets - rx_packets
        
        # Calculate Gbps from the byte count (total_bytes * 8 / duration)
        # Or just trust the packet count for loss %
        
        print("\n--- RESULTS (100Gbps Test) ---")
        print(f"Tx Packets (Port 1): {tx_packets:,}")
        print(f"Rx Packets (Port 0): {rx_packets:,}")
        print(f"Lost Packets:        {lost:,}")
        
        if tx_packets > 0:
            loss_pct = (lost / tx_packets) * 100
            print(f"Loss Percentage:     {loss_pct:.4f}%")
            
            if loss_pct < 0.01:
                print("STATUS: PASSED (Full 100G Throughput)")
            else:
                print("STATUS: PACKET LOSS DETECTED")

    except STLError as e:
        print(f"TRex Error: {e}")
    finally:
        c.disconnect()

if __name__ == "__main__":
    main()
