import sys
import os
import time

# --- SETUP PATHS ---
CURRENT_PATH = os.path.dirname(os.path.realpath(__file__))
TREX_LIB_PATH = os.path.abspath(os.path.join(CURRENT_PATH, '../automation/trex_control_plane/interactive'))
if TREX_LIB_PATH not in sys.path:
    sys.path.insert(0, TREX_LIB_PATH)
from trex_stl_lib.api import *

# =========================================================================
#  CONFIGURATION
# =========================================================================

# ROUTER INTERFACES (Gateway MACs)
# 11.11.11.1 (Router Port facing TRex P0)
ROUTER_MAC_11 = "00:32:17:75:A8:80" 
# 12.12.12.1 (Router Port facing TRex P1)
ROUTER_MAC_12 = "00:32:17:75:A8:84"

def main():
    c = STLClient()
    
    try:
        print("1. Connecting to TRex...")
        c.connect()
        c.acquire(ports=[0, 1], force=True)
        c.reset(ports=[0, 1])
        c.clear_stats()

        print("2. Verifying Cabling (MAC Check)...")
        port_info = c.get_port_info(ports=[0, 1])
        trex_p0_mac = port_info[0]['hw_mac']
        trex_p1_mac = port_info[1]['hw_mac']

        # --- SETUP IPs ---
        # TRex P0 claims 11.11.11.2, sends to Router 11.11.11.1
        TREX_IP_P0 = "11.11.11.2"
        ROUTER_IP_P0 = "11.11.11.1"
        TARGET_MAC_P0 = ROUTER_MAC_11

        # TRex P1 claims 12.12.12.2, sends to Router 12.12.12.1
        TREX_IP_P1 = "12.12.12.2"
        ROUTER_IP_P1 = "12.12.12.1"
        TARGET_MAC_P1 = ROUTER_MAC_12

        print(f"   TRex P0 ({TREX_IP_P0}) -> Router ({ROUTER_IP_P0} @ {TARGET_MAC_P0})")
        print(f"   TRex P1 ({TREX_IP_P1}) -> Router ({ROUTER_IP_P1} @ {TARGET_MAC_P1})")

        # --- STEP 3: CLAIM IPs (Gratuitous ARP) ---
        print("\n3. Sending Gratuitous ARP to update Router tables...")
        c.set_service_mode(ports=[0, 1], enabled=True)
        
        # FIX: Define raw Scapy packets (No STLPktBuilder wrapper here)
        arp_p0 = Ether(src=trex_p0_mac, dst="ff:ff:ff:ff:ff:ff") / \
                 ARP(op=2, psrc=TREX_IP_P0, hwsrc=trex_p0_mac, 
                     pdst=TREX_IP_P0, hwdst=trex_p0_mac)

        arp_p1 = Ether(src=trex_p1_mac, dst="ff:ff:ff:ff:ff:ff") / \
                 ARP(op=2, psrc=TREX_IP_P1, hwsrc=trex_p1_mac, 
                     pdst=TREX_IP_P1, hwdst=trex_p1_mac)

        # Send the packets
        c.push_packets(ports=[0], pkts=[arp_p0])
        c.push_packets(ports=[1], pkts=[arp_p1])
        
        time.sleep(1)
        c.set_service_mode(ports=[0, 1], enabled=False)

        # --- STEP 4: TRAFFIC ---
        print("\n4. Creating Traffic Stream...")
        # Path: TRex P0 (11.11.11.2) -> Router (11.11.11.1) -> [Routing] -> Router (12.12.12.1) -> TRex P1 (12.12.12.2)
        
        # Note: We DO use STLPktBuilder here for the high-speed stream
        pkt = STLPktBuilder(
            pkt = Ether(src=trex_p0_mac, dst=TARGET_MAC_P0) / 
                  IP(src=TREX_IP_P0, dst=TREX_IP_P1) / 
                  UDP(dport=1234, sport=1234) /
                  ('x' * 1400)
        )
        
        s0 = STLStream(packet=pkt, mode=STLTXCont())
        c.add_streams(s0, ports=[0])

        print("5. Starting Test (50Gbps Target)...")
        try:
            c.start(ports=[0], mult="50gbps", duration=30)
        except STLError:
             print("   [!] 50Gbps not supported by hardware. Fallback to 100%.")
             c.start(ports=[0], mult="100%", duration=30)

        c.wait_on_traffic(ports=[0])

        # --- STEP 5: RESULTS ---
        time.sleep(1)
        stats = c.get_stats()
        
        opackets_p0 = stats[0]['opackets']
        ipackets_p1 = stats[1]['ipackets']
        lost = opackets_p0 - ipackets_p1

        print("\n--- TEST RESULTS ---")
        print(f"Tx Packets (Port 0): {opackets_p0:,}")
        print(f"Rx Packets (Port 1): {ipackets_p1:,}")
        print(f"Lost Packets:        {lost:,}")

        if opackets_p0 > 0:
            if lost == 0:
                print("STATUS: SUCCESS (No Loss)")
            else:
                loss_pct = (lost / opackets_p0) * 100
                print(f"STATUS: PACKET LOSS ({loss_pct:.2f}%)")
                if loss_pct > 99:
                    print("DEBUG: 100% Loss. Check that cabling isn't swapped (P0 plugged into P1's port).")

    except STLError as e:
        print(f"TRex Error: {e}")
    finally:
        c.disconnect()

if __name__ == "__main__":
    main()
