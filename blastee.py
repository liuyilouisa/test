#!/usr/bin/env python3

import time
import threading
from struct import pack
import switchyard
from switchyard.lib.address import *
from switchyard.lib.packet import *
from switchyard.lib.userlib import *


class Blastee:
    def __init__(
            self,
            net: switchyard.llnetbase.LLNetBase,
            blasterIp,
            num
    ):
        self.net = net
        self.blasterIp = blasterIp
        self.num = int(num)
        self.recvCount = 0
        self.recvPacket = set()

    def handle_packet(self, recv: switchyard.llnetbase.ReceivedPacket):
        _, fromIface, packet = recv
        log_debug(f"I got a packet from {fromIface}")
        log_debug(f"Pkt: {packet}")
        del packet[Ethernet]
        del packet[IPv4]
        del packet[UDP]
        
        seqNum = int.from_bytes(packet[0].to_bytes(4), byteorder='big')
        if seqNum not in self.recvPacket:
            self.recvPacket.add(seqNum)
            self.recvCount += 1
            log_debug(f"Received packet {seqNum}")
        
        ack = Ethernet()+IPv4(protocol=IPProtocol.UDP)+UDP()
        ack[0].src = "20:00:00:00:01"
        ack[0].dst = "40:00:00:00:02"
        ack[1].ttl = 64
        ack[1].src = IPv4Address("192.168.200.1")
        ack[1].dst = self.blasterIp
        ack+=RawPacketContents(packet[0].to_bytes()[:4])
        content = packet[0].to_bytes()[6:]+bytes(8)
        content = content[:8]
        ack+=RawPacketContents(content)
        self.net.send_packet(fromIface, ack)
        if self.recvCount == self.num:
            self.shutdown()
        

    def start(self):
        '''A running daemon of the blastee.
        Receive packets until the end of time.
        '''
        while True:
            try:
                recv = self.net.recv_packet(timeout=1.0)
            except NoPackets:
                continue
            except Shutdown:
                break

            self.handle_packet(recv)

        self.shutdown()

    def shutdown(self):
        self.net.shutdown()


def main(net, **kwargs):
    blastee = Blastee(net, **kwargs)
    blastee.start()
