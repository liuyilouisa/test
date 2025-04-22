#!/usr/bin/env python3

import time
from random import randint
import switchyard
from switchyard.lib.address import *
from switchyard.lib.packet import *
from switchyard.lib.userlib import *
import struct
import queue


class Item:
    def __init__(self, pkt, sequencenumber, time):
        self.pkt = pkt
        self.sequencenumber = sequencenumber
        self.acked = False


class Blaster:
    def __init__(self, net: switchyard.llnetbase.LLNetBase, blasteeIp, num, length="100", senderWindow="5", timeout="300", recvTimeout="100"):
        self.net = net
        self.blasteeIp = IPv4Address(blasteeIp)
        self.num = int(num)
        self.length = int(length)
        self.senderWindow = int(senderWindow)
        self.timeout = float(int(timeout) / 1000)
        self.recvTimeout = float(int(recvTimeout) / 1000)
        self.queue = []
        self.timestamp = time.time()
        self.retranqueue = queue.Queue()
        self.left = 1
        self.right = 0

        # 统计量
        self.starttime = 0  # 第一个包的发送时间
        self.totaltime = 0  # 总传输时间
        self.retrantimes = 0  # 重传次数
        self.timeouttimes = 0  # 超时次数
        self.allbytes = 0  # 发送的总字节数
        self.allbytesonce = 0  # 不包括重传的发送字节数
        self.throughput = 0  # 吞吐量
        self.goodput = 0  # 有效吞吐量

    def handle_packet(self, recv: switchyard.llnetbase.ReceivedPacket):
        _, fromIface, packet = recv
        log_debug("I got a packet")
        rawbytes = packet[3].to_bytes()
        rawsequencenumber = rawbytes[0:4]
        sequencenumber = struct.unpack('!I', rawsequencenumber)[0]
        log_info(f'receive the sequencenumber{sequencenumber} ack_packet')

        if self.left > self.right:
            log_info("the ack_packet is repeated")
            return

        if sequencenumber == self.queue[0].sequencenumber:
            self.queue[0].acked = True
            i = 0
            while i < len(self.queue) and self.queue[i].acked:
                i += 1
                self.left += 1
                self.timestamp = time.time()
            if i < len(self.queue):
                self.queue = self.queue[i:]
            else:
                self.queue = []
        else:
            for item in self.queue:
                if item.sequencenumber == sequencenumber:
                    item.acked = True
                    break

        log_info(f'now left is {self.left} right is {self.right}')
        if self.left == self.num + 1:
            self.totaltime = time.time() - self.starttime
            self.throughput = self.allbytes / self.totaltime
            self.goodput = self.allbytesonce / self.totaltime
            log_info(f"totaltime{self.totaltime:.4f} throughput{self.throughput:.4f} goodput{self.goodput:.4f}")
            log_info(f"retrantimes{self.retrantimes} timeouttimes{self.timeouttimes}")
            log_info(f"allbytes{self.allbytes} allbytesonce{self.allbytesonce}")
            log_info("all down!")
            self.shutdown()
            return

    def handle_no_packet(self):
        log_debug("Didn't receive anything")
        if self.left == self.num + 1:
            log_info("all down!")
            return

        if not self.retranqueue.empty():
            log_info('going to retransmit')
            item = self.retranqueue.get()
            log_info(f'retransmit the sequencenumber{item.sequencenumber} packet')
            self.net.send_packet('blaster-eth0', item.pkt)
            self.retrantimes += 1
            self.allbytes += self.length
            return

        if self.right < self.num and self.right - self.left + 1 < self.senderWindow:
            # 创建数据包
            pkt = Ethernet() + IPv4() + UDP()
            pkt[1].protocol = IPProtocol.UDP
            pkt[1].src = IPv4Address("192.168.100.1")
            pkt[1].dst = self.blasteeIp
            pkt[1].ttl = 64
            pkt[0].src = EthAddr("10:00:00:00:00:01")
            pkt[0].dst = EthAddr("40:00:00:00:00:01")
            log_info('right is moving')
            self.right += 1
            sequencenumber = self.right
            rawsequencenumber = sequencenumber.to_bytes(4, byteorder='big')
            rawlength = self.length.to_bytes(2, byteorder='big')
            rawcontent = bytes([0] * self.length)
            pkt += RawPacketContents(rawsequencenumber)
            pkt += RawPacketContents(rawlength)
            pkt += RawPacketContents(rawcontent)
            log_info(f'first time send_packet with sequencenumber{sequencenumber}')
            self.net.send_packet('blaster-eth0', pkt)
            if sequencenumber == 1:
                self.starttime = time.time()
            self.queue.append(Item(pkt, sequencenumber, self.starttime))
            self.allbytes += self.length
            self.allbytesonce += self.length
            log_info(f'now left is {self.left} right is {self.right}')
        elif time.time() - self.timestamp >= self.timeout:
            log_info("timeout!!!")
            self.timeouttimes += 1
            for item in self.queue:
                if not item.acked:
                    self.retranqueue.put(item)
            log_info(f'timeout and retransmit the sequencenumber{self.retranqueue.queue[0].sequencenumber} packet')
            self.net.send_packet('blaster-eth0', self.retranqueue.queue[0].pkt)
            self.retrantimes += 1
            self.allbytes += self.length
            self.retranqueue.get()

    def start(self):
        '''A running daemon of the blaster.
        Receive packets until the end of time.
        '''
        while True:
            try:
                recv = self.net.recv_packet(timeout=self.recvTimeout)
            except NoPackets:
                self.handle_no_packet()
                continue
            except Shutdown:
                break

            self.handle_packet(recv)

        self.shutdown()

    def shutdown(self):
        self.net.shutdown()


def main(net, **kwargs):
    blaster = Blaster(net, **kwargs)
    blaster.start()