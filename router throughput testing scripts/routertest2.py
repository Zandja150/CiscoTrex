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
#  CONFIGURATION (Matched to NCS 540x Config)
# =========================================================================

# Router MACs (Gateway)
ROUTER_MAC_P0 = "00:32:17:75:A8:80"  # Interface 11.11.11.1
ROUTER_MAC_P1 = "00:32:17:75:A8:84"  # Interface 12.12.12.1

# TRex Interface IPs (The "Next Hops" defined in your static routes)
TREX_IP_P0 = "11.11.11.2"
TREX_IP_P1 = "12.12.12.2"

# Traffic Flow IPs (Based on your Static Routes)
# We send TO 48.0.0.1 so the router hits the "48.0.0.0/8 -> 12.12.12.2" route
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

        print("2. Getting TRex HW MACs...")
        port_info = c.get_port_info(ports=[0, 1])
        trex_p0_mac = port_info[0]['hw_mac']
        trex_p1_mac = port_info[1]['hw_mac']

        print(f"   TRex P0 ({TREX_IP_P0}) -> Router ({ROUTER_MAC_P0})")
        print(f"   TRex P1 ({TREX_IP_P1}) -> Router ({ROUTER_MAC_P1})")

        # --- STEP 3: GRATUITOUS ARP (Essential for Next-Hop Resolution) ---
        print("\n3. Sending Gratuitous ARP to populate Router ARP Table...")
        c.set_service_mode(ports=[0, 1], enabled=True)
        
        # Port 0 says: "I am 11.11.11.2"
        arp_p0 = Ether(src=trex_p0_mac, dst="ff:ff:ff:ff:ff:ff") / \
                 ARP(op=2, psrc=TREX_IP_P0, hwsrc=trex_p0_mac, 
                     pdst=TREX_IP_P0, hwdst=trex_p0_mac)

        # Port 1 says: "I am 12.12.12.2" (CRITICAL: Router needs this to forward packets out)
        arp_p1 = Ether(src=trex_p1_mac, dst="ff:ff:ff:ff:ff:ff") / \
                 ARP(op=2, psrc=TREX_IP_P1, hwsrc=trex_p1_mac, 
                     pdst=TREX_IP_P1, hwdst=trex_p1_mac)

        # Send burst of ARPs to ensure Router sees them
        for _ in range(5):
            c.push_packets(ports=[0], pkts=[arp_p0])
            c.push_packets(ports=[1], pkts=[arp_p1])
            time.sleep(0.2)
            
        c.set_service_mode(ports=[0, 1], enabled=False)
        print("   ARPs sent.")

        # --- PAUSE FOR VERIFICATION ---
        print("\n" + "="*60)
        print(" ACTION REQUIRED: CHECK ROUTER ARP TABLE NOW!")
        print(f" Run 'show arp' on the NCS 540x.")
        print(f" Verify {TREX_IP_P0} maps to {trex_p0_mac}")
        print(f" Verify {TREX_IP_P1} maps to {trex_p1_mac}")
        print("="*60)
        input("Press Enter to start 50Gbps traffic...")

        # --- STEP 4: TRAFFIC STREAM ---
        print("\n4. Creating Traffic Stream...")
        # Path: TRex P0 -> Router (Matches Static Route 48.0.0.0/8) -> TRex P1
        
        pkt = STLPktBuilder(
            pkt = Ether(src=trex_p0_mac, dst=ROUTER_MAC_P0) / 
                  IP(src=SRC_IP, dst=DST_IP) / 
                  UDP(dport=1234, sport=1234) /
                  ('x' * 1400)
        )
        
        s0 = STLStream(packet=pkt, mode=STLTXCont())
        c.add_streams(s0, ports=[0])

        print("5. Starting Traffic...")
        try:
            c.start(ports=[0], mult="50gbps", duration=30)
        except STLError:
             print("   [!] Hardware limit reached. Switching to 100% Line Rate.")
             c.start(ports=[0], mult="100%", duration=30)

        c.wait_on_traffic(ports=[0])

        # --- RESULTS ---
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
            loss_pct = (lost / opackets_p0) * 100
            if lost == 0:
                print("STATUS: SUCCESS (Full Throughput)")
            else:
                print(f"STATUS: PACKET LOSS ({loss_pct:.2f}%)")
                if loss_pct > 99:
                    print("DEBUG: 100% Loss implies Router dropped packets at egress.")
                    print(f"       Ensure Router has ARP entry for Next-Hop {TREX_IP_P1}")

    except STLError as e:
        print(f"TRex Error: {e}")
    finally:
        c.disconnect()

if __name__ == "__main__":
    main()
