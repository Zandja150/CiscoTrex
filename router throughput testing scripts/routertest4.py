import sys
import os
import time

CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))
TREX_LIB_PATH = os.path.abspath(os.path.join(CURRENT_PATH, '../automation/trex_control_plane/interactive'))
if TREX_LIB_PATH not in sys.path:
    sys.path.insert(0, TREX_LIB_PATH)
from trex_stl_lib.api import *

# =========================================================================
#  CONFIGURATION (Based on your 'show arp' Output)
# =========================================================================

# --- ROUTER MAC ADDRESSES (Hardcoded from your output) ---
# interface HundredGigE0/0/1/0 (11.11.11.1) -> MAC 0032.1775.a880
ROUTER_MAC_11 = "00:32:17:75:a8:80"

# interface HundredGigE0/0/1/1 (12.12.12.1) -> MAC 0032.1775.a884
ROUTER_MAC_12 = "00:32:17:75:a8:84"

# --- TRAFFIC FLOW STRATEGY ---
# We will send traffic FROM Port 1 (11.x network) -> TO Router.
# Destination IP: 48.0.0.1.
# Router sees 48.x, looks at static route: "48.0.0.0/8 -> 12.12.12.2".
# Router forwards to 12.12.12.2 (which is TRex Port 0).

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

        # Get TRex Interface MACs
        port_info = c.get_port_info(ports=[0, 1])
        trex_mac_p1 = port_info[1]['hw_mac'] # Sender (connected to 11.x)

        print(f"   Sender: TRex Port 1 ({trex_mac_p1}) -> Router ({ROUTER_MAC_11})")
        print(f"   Target: Router -> TRex Port 0 (via Route 48.0.0.0/8)")

        # --- STEP 2: KEEP ARP ALIVE (Ping Trick) ---
        # Even though ARP is up now, we ping to ensure it doesn't expire during the test.
        # We assume Port 0 = 12.12.12.2 and Port 1 = 11.11.11.2 based on your cabling.
        
        c.set_service_mode(ports=[0, 1], enabled=True)
        
        # Configure IPs so TRex can reply to ARP if Router asks again
        c.set_l3_mode(port=0, src_ipv4="12.12.12.2", dst_ipv4="12.12.12.1")
        c.set_l3_mode(port=1, src_ipv4="11.11.11.2", dst_ipv4="11.11.11.1")
        
        print("\n2. Refreshing ARP (Sending Pings)...")
        try:
            # Ping Router 11.1 from Port 1
            c.ping_ip(src_port=1, dst_ip="11.11.11.1", pkt_size=64, count=3)
            # Ping Router 12.1 from Port 0
            c.ping_ip(src_port=0, dst_ip="12.12.12.1", pkt_size=64, count=3)
            print("   Pings sent. ARP tables refreshed.")
        except STLError:
            pass # Ignore ping errors, we are relying on existing ARP state mainly

        c.set_service_mode(ports=[0, 1], enabled=False)

        # --- STEP 3: TRAFFIC ---
        print("\n3. Starting 50Gbps Stream...")
        
        # Packet: 
        # Src: TRex Port 1
        # Dst: Router 11.11.11.1 MAC (00:32:17:75:a8:80)
        # IP Dst: 48.0.0.1 (Triggers static route to 12.x side)
        
        pkt = STLPktBuilder(
            pkt = Ether(src=trex_mac_p1, dst=ROUTER_MAC_11) / 
                  IP(src=SRC_IP, dst=DST_IP) / 
                  UDP(dport=1234, sport=1234) /
                  ('x' * 1400)
        )
        
        s1 = STLStream(packet=pkt, mode=STLTXCont())
        
        # Add stream to Port 1 (Sender)
        c.add_streams(s1, ports=[1])

        try:
            c.start(ports=[1], mult="50gbps", duration=30)
        except STLError:
            print("   [!] Hardware limit. Running at 100% Line Rate.")
            c.start(ports=[1], mult="100%", duration=30)
            
        c.wait_on_traffic(ports=[1])

        # --- STEP 4: RESULTS ---
        time.sleep(1)
        stats = c.get_stats()
        opackets = stats[1]['opackets'] # Sent from Port 1
        ipackets = stats[0]['ipackets'] # Received on Port 0
        lost = opackets - ipackets

        print("\n--- RESULTS ---")
        print(f"Tx Packets (Port 1): {opackets:,}")
        print(f"Rx Packets (Port 0): {ipackets:,}")
        print(f"Lost:                {lost:,}")
        
        if ipackets > 0:
            print("STATUS: SUCCESS! Traffic is flowing.")
        else:
            print("STATUS: FAILED.")

    except STLError as e:
        print(f"TRex Error: {e}")
    finally:
        c.disconnect()

if __name__ == "__main__":
    main()
