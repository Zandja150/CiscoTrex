import sys
import os
import time

CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))
TREX_LIB_PATH = os.path.abspath(os.path.join(CURRENT_PATH, '../automation/trex_control_plane/interactive'))
if TREX_LIB_PATH not in sys.path:
    sys.path.insert(0, TREX_LIB_PATH)
from trex_stl_lib.api import *

# =========================================================================
#  STATIC IP CONFIGURATION (Based on your working setup)
# =========================================================================
# Port 0 (Receiver)
TREX_IP_P0   = "12.12.12.2"
ROUTER_IP_P0 = "12.12.12.1"

# Port 1 (Sender)
TREX_IP_P1   = "11.11.11.2"
ROUTER_IP_P1 = "11.11.11.1"

# Traffic Flow
SRC_IP = "16.0.0.1"
DST_IP = "48.0.0.1"
# =========================================================================

def main():
    c = STLClient()
    
    # --- USER INPUT SECTION ---
    print("\n=== TRex Router Test Configuration ===")
    
    # Ask for Router MACs
    print("Please enter the Router MAC addresses found in 'show arp':")
    router_mac_11 = input(f"Enter Router MAC for {ROUTER_IP_P1} (Sender Side): ").strip()
    router_mac_12 = input(f"Enter Router MAC for {ROUTER_IP_P0} (Receiver Side): ").strip()

    # Ask for Duration
    try:
        duration_input = input("Enter test duration in seconds (Default 30): ").strip()
        test_duration = int(duration_input) if duration_input else 30
    except ValueError:
        print("Invalid number. Defaulting to 30 seconds.")
        test_duration = 30

    # Ask for Rate
    rate_input = input("Enter transmission rate (e.g., '100gbps', '50gbps', '100%'): ").strip()
    if not rate_input:
        rate_input = "100%" # Default
        print("No rate entered. Defaulting to 100%.")

    print("\n========================================")

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
            # Ping Router from Receiver Port (Port 0) so Router knows where to send the traffic
            c.ping_ip(src_port=0, dst_ip=ROUTER_IP_P0, pkt_size=64, count=5)
            # Ping Router from Sender Port (Port 1) just in case
            c.ping_ip(src_port=1, dst_ip=ROUTER_IP_P1, pkt_size=64, count=3)
            print("   ARP refreshed.")
        except STLError:
            pass 

        time.sleep(1)
        c.set_service_mode(ports=[0, 1], enabled=False)

        # --- STEP 3: TRAFFIC ---
        print(f"\n3. Starting Traffic for {test_duration} seconds at {rate_input}...")
        print(f"   Sender: Port 1 -> Router ({router_mac_11})")
        print(f"   Target: Router -> Port 0 ({router_mac_12}) via Route")
        
        # Build Packet using User Input MACs
        # Note: We send TO the 11.11.11.1 MAC. The Router forwards to the 12.12.12.1 side.
        pkt = STLPktBuilder(
            pkt = Ether(src=sender_mac, dst=router_mac_11) / 
                  IP(src=SRC_IP, dst=DST_IP) / 
                  UDP(dport=1234, sport=1234) /
                  ('x' * 1400)
        )
        
        s1 = STLStream(packet=pkt, mode=STLTXCont())
        c.add_streams(s1, ports=[1])

        # --- THE PUSH ---
        try:
            c.start(ports=[1], mult=rate_input, duration=test_duration)
        except STLError as e:
            print(f"   [!] Error starting traffic: {e}")
            print("       (Check if your requested rate exceeds hardware limits)")
            return
            
        c.wait_on_traffic(ports=[1])

        # --- STEP 4: RESULTS ---
        time.sleep(1)
        stats = c.get_stats()
        
        tx_packets = stats[1]['opackets'] # Sent from Port 1
        rx_packets = stats[0]['ipackets'] # Received on Port 0
        lost = tx_packets - rx_packets
        
        print("\n--- TEST RESULTS ---")
        print(f"Tx Packets (Port 1): {tx_packets:,}")
        print(f"Rx Packets (Port 0): {rx_packets:,}")
        print(f"Lost Packets:        {lost:,}")
        
        if tx_packets > 0:
            loss_pct = (lost / tx_packets) * 100
            print(f"Loss Percentage:     {loss_pct:.4f}%")
            
            if loss_pct < 0.01:
                print("STATUS: PASSED (No Significant Loss)")
            else:
                print("STATUS: PACKET LOSS DETECTED")

    except STLError as e:
        print(f"TRex Error: {e}")
    finally:
        c.disconnect()

if __name__ == "__main__":
    main()