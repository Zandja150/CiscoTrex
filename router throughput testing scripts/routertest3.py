import sys
import os
import time

CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))
TREX_LIB_PATH = os.path.abspath(os.path.join(CURRENT_PATH, '../automation/trex_control_plane/interactive'))
if TREX_LIB_PATH not in sys.path:
    sys.path.insert(0, TREX_LIB_PATH)
from trex_stl_lib.api import *

# --- CONFIG ---
# Router Interfaces
ROUTER_MAC_P0 = "00:32:17:75:A8:80" # 11.11.11.1
ROUTER_MAC_P1 = "00:32:17:75:A8:84" # 12.12.12.1

# Traffic Targets (Matched to your Static Routes)
# Sending to 48.0.0.1 hits the "48.0.0.0/8 -> 12.12.12.2" route
SRC_IP = "16.0.0.1" 
DST_IP = "48.0.0.1"
# --------------

def main():
    c = STLClient()
    try:
        c.connect()
        c.acquire(ports=[0, 1], force=True)
        c.reset(ports=[0, 1])
        c.clear_stats()

        print("1. Getting TRex MACs...")
        port_info = c.get_port_info(ports=[0, 1])
        print(f"   TRex Port 1 MAC: {port_info[1]['hw_mac']}")
        print("   ^ MAKE SURE THIS MAC IS IN YOUR ROUTER STATIC ARP CONFIG!")

        print("2. Starting Traffic (50Gbps)...")
        # Simple Stream: Port 0 -> Router MAC -> Router Routes to Port 1
        pkt = STLPktBuilder(
            pkt = Ether(src=port_info[0]['hw_mac'], dst=ROUTER_MAC_P0) / 
                  IP(src=SRC_IP, dst=DST_IP) / 
                  UDP(dport=1234, sport=1234) / ('x' * 1400)
        )
        
        s0 = STLStream(packet=pkt, mode=STLTXCont())
        c.add_streams(s0, ports=[0])

        try:
            c.start(ports=[0], mult="50gbps", duration=30)
        except STLError:
            c.start(ports=[0], mult="100%", duration=30)
            
        c.wait_on_traffic(ports=[0])

        stats = c.get_stats()
        opackets = stats[0]['opackets']
        ipackets = stats[1]['ipackets']
        
        print("\n--- RESULTS ---")
        print(f"Tx: {opackets:,}")
        print(f"Rx: {ipackets:,}")
        
        if opackets > 0 and ipackets == 0:
            print("STATUS: STILL FAILING. Router is dropping packets.")
            print("Check: 1. Is static ARP configured?")
            print("       2. Does 'show ip route 48.0.0.1' show 12.12.12.2?")
        elif ipackets > 0:
            print("STATUS: SUCCESS! Traffic is flowing.")

    except STLError as e:
        print(f"TRex Error: {e}")
    finally:
        c.disconnect()

if __name__ == "__main__":
    main()
