#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# __author__ == 'LossCuts'

"""
Minimum TFTP server & client.
Support only RFC 1350. No ascii mode.
Python3.x.

version 20160711

Download URL: https://github.com/LossCuts/minimumTFTP

usage:
----------------------------------------------
## >>> import minimumTFTP

## server running
## >>> tftpServer = minimumTFTP.Server('C:\\server_TFTP_Directory')
## >>> tftpServer.run()

## client running
##  arg1: server_IP_address
##  arg2: client_directory
##  arg3: get or put filename
## >>> tftpClient = minimumTFTP.Client(arg1, arg2, arg3)

## get
## >>> tftpClient.get()

## put
## >>> tftpClient.put()
----------------------------------------------
"""

import socket
import struct
import os
import time
import threading
import sys


class Server(object):
    def __init__(self, d_path):
        global serverDir, serverLocalSocket, remoteDict
        serverDir = d_path
        serverLocalSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        serverLocalSocket.bind(('', 69))
        remoteDict = {}

    @staticmethod
    def run():
        while True:

            try:
                data, remote_socket = serverLocalSocket.recvfrom(4096)

                if remote_socket in remoteDict:
                    remoteDict[remote_socket].run_proc(data)
                else:
                    remoteDict[remote_socket] = PacketProcess(remote_socket)
                    remoteDict[remote_socket].run_proc(data)

            except:
                pass


class WatchDog(threading.Thread):
    def __init__(self, owner):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.resetEvent = threading.Event()
        self.stopEvent = threading.Event()
        self.owner = owner

    def run(self):
        time_count = 0

        while True:

            if self.stopEvent.isSet():
                break

            if time_count % 5 == 0 and 0 < time_count < 25:
                remoteDict[self.owner].re_send()
                print('Resend data.(%s:%s)' % (self.owner[0], self.owner[1]))

            elif time_count >= 25:
                remoteDict[self.owner].clear('Session timeout. (%s:%s)' % (self.owner[0], self.owner[1]))
                break

            if self.resetEvent.isSet():
                time_count = 0
                self.resetEvent.clear()

            time.sleep(1)
            time_count += 1

    def count_reset(self):
        self.resetEvent.set()

    def stop(self):
        self.stopEvent.set()


class PacketProcess(object):
    def __init__(self, remote_socket):
        self.remoteSocket = remote_socket
        self.endFrag = False
        self.watchdog = WatchDog(self.remoteSocket)
        self.sendFile = None
        self.rcvFile = None
        self.totalDatalen = None
        self.countBlock = None
        self.sendPacket = None

    def run_proc(self, data):
        self.watchdog.count_reset()
        opcode = struct.unpack('!H', data[0:2])[0]

        # Opcode 1 [ Read request ]
        #
        #           2 bytes    string   1 byte     string   1 byte
        #           -----------------------------------------------
        #    RRQ   |  01   |  Filename  |   0  |    Mode    |   0  |
        #           -----------------------------------------------

        if opcode == 1:

            filename = bytes.decode(data[2:].split(b'\x00')[0])
            file_path = os.path.join(serverDir, filename)
            print('Read request from:%s:%s, filename:%s'
                  % (self.remoteSocket[0], self.remoteSocket[1], filename))

            if os.path.isfile(file_path):
                try:
                    self.sendFile = open(file_path, 'rb')
                except:
                    serverLocalSocket.sendto(errFileopen, self.remoteSocket)
                    self.clear('Can not read file. Session closed. (%s:%s)'
                               % (self.remoteSocket[0], self.remoteSocket[1]))
                    return None

                data_chunk = self.sendFile.read(512)
                self.totalDatalen = len(data_chunk)
                self.countBlock = 1

                self.sendPacket = struct.pack(b'!2H', 3, self.countBlock) + data_chunk
                serverLocalSocket.sendto(self.sendPacket, self.remoteSocket)

                if len(data_chunk) < 512:
                    self.endFrag = True

                self.watchdog.start()

            else:
                serverLocalSocket.sendto(errNofile, self.remoteSocket)
                self.clear('Requested file not found. Session closed. (%s:%s)'
                           % (self.remoteSocket[0], self.remoteSocket[1]))

        # Opcode 2 [ Write request ]
        #
        #          2 bytes    string   1 byte     string   1 byte
        #          -----------------------------------------------
        #   WRQ   |  02   |  Filename  |   0  |    Mode    |   0  |
        #          -----------------------------------------------

        elif opcode == 2:

            filename = bytes.decode(data[2:].split(b'\x00')[0])
            file_path = os.path.join(serverDir, filename)
            print('Write request from:%s:%s, filename:%s'
                  % (self.remoteSocket[0], self.remoteSocket[1], filename))

            if os.path.isfile(file_path):
                serverLocalSocket.sendto(errFileExists, self.remoteSocket)
                self.clear('File already exist. Session closed. (%s:%s)'
                           % (self.remoteSocket[0], self.remoteSocket[1]))

            else:
                try:
                    self.rcvFile = open(file_path, 'wb')
                except:
                    serverLocalSocket.sendto(errFileopen, self.remoteSocket)
                    self.clear('Can not open file. Session closed. (%s:%s)'
                               % (self.remoteSocket[0], self.remoteSocket[1]))
                    return None

                self.totalDatalen = 0
                self.countBlock = 1

                self.sendPacket = struct.pack(b'!2H', 4, 0)
                serverLocalSocket.sendto(self.sendPacket, self.remoteSocket)

                self.watchdog.start()

        # Opcode 3 [ Data ]
        #
        #          2 bytes    2 bytes       n bytes
        #          ---------------------------------
        #   DATA  | 03    |   Block #  |    Data    |
        #          ---------------------------------

        elif opcode == 3:

            block_no = struct.unpack('!H', data[2:4])[0]
            data_pay_load = data[4:]
            self.totalDatalen += len(data_pay_load)

            if block_no == self.countBlock:
                try:
                    self.rcvFile.write(data_pay_load)
                except:
                    serverLocalSocket.sendto(errFilewrite, self.remoteSocket)
                    self.clear('Can not write data. Session closed. (%s:%s)'
                               % (self.remoteSocket[0], self.remoteSocket[1]))
                    return None

                self.countBlock += 1
                if self.countBlock == 65536:
                    self.countBlock = 0

                self.sendPacket = struct.pack(b'!2H', 4, block_no)
                serverLocalSocket.sendto(self.sendPacket, self.remoteSocket)

                self.watchdog.count_reset()

                if len(data_pay_load) < 512:
                    self.clear('Data receive finish. %s bytes (%s:%s)'
                               % (self.totalDatalen, self.remoteSocket[0],
                                  self.remoteSocket[1]))

            else:
                print('Receive wrong block. Resend data. (%s:%s)'
                      % (self.remoteSocket[0], self.remoteSocket[1]))

        # Opcode 4 [ ack ]
        #
        #          2 bytes    2 bytes
        #          -------------------
        #   ACK   | 04    |   Block #  |
        #          --------------------

        elif opcode == 4:

            if self.endFrag:
                self.clear('Data send finish. %s bytes (%s:%s)'
                           % (self.totalDatalen, self.remoteSocket[0],
                              self.remoteSocket[1]))

            else:
                block_no = struct.unpack('!H', data[2:4])[0]

                if block_no == self.countBlock:
                    try:
                        data_chunk = self.sendFile.read(512)
                    except:
                        data_chunk = ''

                    data_len = len(data_chunk)
                    self.totalDatalen += data_len
                    self.countBlock += 1
                    if self.countBlock == 65536:
                        self.countBlock = 0

                    self.sendPacket = struct.pack(b'!2H', 3, self.countBlock) + data_chunk
                    serverLocalSocket.sendto(self.sendPacket, self.remoteSocket)

                    self.watchdog.count_reset()

                    if data_len < 512:
                        self.endFrag = True

                else:
                    print('Receive wrong block. Resend data. (%s:%s)'
                          % (self.remoteSocket[0], self.remoteSocket[1]))

        # Opcode 5 [ error ]
        #
        #          2 bytes  2 bytes        string    1 byte
        #          ----------------------------------------
        #   ERROR | 05    |  ErrorCode |   ErrMsg   |   0  |
        #          ----------------------------------------

        elif opcode == 5:

            err_code = struct.unpack('!H', data[2:4])[0]
            err_string = data[4:-1]
            self.clear('Received error code %s:%s Session closed.(%s:%s)'
                       % (str(err_code), err_string, self.remoteSocket[0],
                          self.remoteSocket[1]))

        #
        # Unknown Opcode
        #

        else:
            serverLocalSocket.sendto(errUnknown, self.remoteSocket)
            self.clear('Unknown error. Session closed.(%s:%s)'
                       % (self.remoteSocket[0], self.remoteSocket[1]))

    def re_send(self):
        serverLocalSocket.sendto(self.sendPacket, self.remoteSocket)

    def clear(self, message):
        try:
            self.sendFile.close()
        except:
            pass
        try:
            self.rcvFile.close()
        except:
            pass

        del remoteDict[self.remoteSocket]
        self.watchdog.stop()
        print(message.strip())


class Client(object):
    def __init__(self, server_ip, client_dir, file_name):
        self.serverIP = server_ip
        self.filePath = os.path.join(client_dir, file_name)
        self.fileName = file_name

        self.clientSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.clientSocket.settimeout(5)
        self.sendPacket = None

    def get(self):

        if os.path.isfile(self.filePath):
            print(self.fileName + ' is alredy exist. Can not start.')
            return None

        # Opcode 1 [ Read request ]
        #
        #          2 bytes    string   1 byte     string   1 byte
        #          -----------------------------------------------
        #   RRQ   |  01   |  Filename  |   0  |    Mode    |   0  |
        #          -----------------------------------------------

        format_rrq = '!H' + str(len(self.fileName)) + 'sB5sB'
        self.sendPacket = struct.pack(format_rrq.encode(), 1, self.fileName.encode(), 0, b'octet', 0)
        self.clientSocket.sendto(self.sendPacket, (self.serverIP, 69))

        try:
            get_file = open(self.filePath, 'wb')
        except:
            print(self.fileName + ' can not open.')
            return None

        total_data_len = 0
        count_block = 1
        err_count = 0
        opcode = None
        remote_socket = None

        while True:

            while err_count < 3:
                try:
                    data, remote_socket = self.clientSocket.recvfrom(4096)
                    opcode = struct.unpack('!H', data[0:2])[0]
                    err_count = 0
                    break
                except:
                    self.clientSocket.sendto(self.sendPacket, (self.serverIP, 69))
                    opcode = 'Timeout'
                    err_count += 1

            # Opcode 3 [ Data ]
            #
            #          2 bytes    2 bytes       n bytes
            #          ---------------------------------
            #   DATA  | 03    |   Block #  |    Data    |
            #          ---------------------------------

            if opcode == 3:

                block_no = struct.unpack('!H', data[2:4])[0]
                if block_no != count_block:
                    self.clientSocket.sendto(errBlockNo, remote_socket)
                    print('Receive wrong block. Session closed.')
                    get_file.close()
                    break

                count_block += 1
                if count_block == 65536:
                    count_block = 1

                data_pay_load = data[4:]

                try:
                    get_file.write(data_pay_load)
                except:
                    self.clientSocket.sendto(errFilewrite, remote_socket)
                    print('Can not write data. Session closed.')
                    get_file.close()
                    break

                total_data_len += len(data_pay_load)
                sys.stdout.write('\rget %s :%s bytes.' % (self.fileName, total_data_len))

                self.sendPacket = struct.pack(b'!2H', 4, block_no)
                self.clientSocket.sendto(self.sendPacket, remote_socket)

                if len(data_pay_load) < 512:
                    sys.stdout.write('\rget %s :%s bytes. finish.' % (self.fileName, total_data_len))
                    get_file.close()
                    break

            elif opcode == 5:

                err_code = struct.unpack('!H', data[2:4])[0]
                err_string = data[4:-1]
                print('Received error code %s : %s' % (str(err_code), bytes.decode(err_string)))
                get_file.close()
                break

            elif opcode == 'Timeout':
                print('Timeout. Session closed.')
                try:
                    get_file.close()
                except:
                    pass
                break

            else:

                print('Unknown error. Session closed.')
                try:
                    get_file.close()
                except:
                    pass
                break

    def put(self):

        if not os.path.isfile(self.filePath):
            print(self.fileName + ' not exist. Can not start.')
            return None

        # Opcode 2 [ Write request ]
        #
        #          2 bytes    string   1 byte     string   1 byte
        #          -----------------------------------------------
        #   WRQ   |  02   |  Filename  |   0  |    Mode    |   0  |
        #          -----------------------------------------------

        format_wrq = '!H' + str(len(self.fileName)) + 'sB5sB'
        wrq_packet = struct.pack(format_wrq.encode(), 2, self.fileName.encode(), 0, b'octet', 0)
        self.clientSocket.sendto(wrq_packet, (self.serverIP, 69))

        try:
            put_file = open(self.filePath, 'rb')
        except:
            print(self.fileName + ' can not open.')
            return None

        end_flag = False
        total_data_len = 0
        count_block = 0

        while True:

            data, remote_socket = self.clientSocket.recvfrom(4096)
            opcode = struct.unpack('!H', data[0:2])[0]

            # Opcode 4 [ ack ]
            #
            #          2 bytes    2 bytes
            #          --------------------
            #   ACK   | 04    |   Block #  |
            #          --------------------

            if opcode == 4:

                if end_flag:
                    put_file.close()
                    sys.stdout.write('\rput %s :%s bytes. finish.' % (self.fileName, total_data_len))
                    break

                block_no = struct.unpack('!H', data[2:4])[0]

                if block_no != count_block:
                    self.clientSocket.sendto(errBlockNo, remote_socket)
                    print('Receive wrong block. Session closed.')
                    put_file.close()
                    break

                block_no += 1
                if block_no == 65536:
                    block_no = 0

                data_chunk = put_file.read(512)

                data_packet = struct.pack(b'!2H', 3, block_no) + data_chunk
                self.clientSocket.sendto(data_packet, remote_socket)

                total_data_len += len(data_chunk)
                sys.stdout.write('\rput %s :%s bytes.' % (self.fileName, total_data_len))

                count_block += 1
                if count_block == 65536:
                    count_block = 0

                if len(data_chunk) < 512:
                    end_flag = True

            elif opcode == 5:

                err_code = struct.unpack('!H', data[2:4])[0]
                err_string = data[4:-1]
                print('Receive error code %s : %s' % (str(err_code), bytes.decode(err_string)))
                put_file.close()
                break

            else:

                print('Unknown error. Session closed.')
                try:
                    put_file.close()
                except:
                    pass
                break


"""
Error Codes

 Value Meaning

 0 Not defined, see error message (if any).
 1 File not found.
 2 Access violation.
 3 Disk full or allocation exceeded.
 4 Illegal TFTP operation.
 5 Unknown transfer ID.
 6 File already exists.
"""

errNofile = struct.pack(b'!2H15sB', 5, 1, b'File not found.', 0)
errFileopen = struct.pack(b'!2H18sB', 5, 2, b'Can not open file.', 0)
errFilewrite = struct.pack(b'!2H19sB', 5, 2, b'Can not write file.', 0)
errBlockNo = struct.pack(b'!2H20sB', 5, 5, b'Unknown transfer ID.', 0)
errFileExists = struct.pack(b'!2H20sB', 5, 6, b'File already exists.', 0)
errUnknown = struct.pack(b'!2H23sB', 5, 4, b'Illegal TFTP operation.', 0)


def test():
    """
    server runnning
        Usage: python -m minimumTFTP -s [directory]

    client get
        Usage: python -m minimumTFTP -g [serverIP] [directory] [filename]

    client put
        Usage: python -m minimumTFTP -p [serverIP] [directory] [filename]
    """

    if '-s' in sys.argv:
        try:
            Server(sys.argv[2]).run()
        except:
            print(sys.exc_info()[0])
            raise

    elif '-g' in sys.argv:
        try:
            Client(sys.argv[2], sys.argv[3], sys.argv[4]).get()
        except:
            print(sys.exc_info()[0])
            raise

    elif '-p' in sys.argv:
        try:
            Client(sys.argv[2], sys.argv[3], sys.argv[4]).put()
        except:
            print(sys.exc_info()[0])
            raise

    elif 'help' in sys.argv:
        print(test.__doc__)
        sys.exit(0)

    else:
        print(test.__doc__)
        sys.exit(0)


if __name__ == '__main__':
    test()
