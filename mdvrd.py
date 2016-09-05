#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp.web
import addict
import time
import sys
import os
import json
import datetime
import argparse
import pprint
import socket
import struct
import functools
import uuid
import zlib

# default false, can be changed via program arguments (-v)
DEBUG_ON = False

# the standard interval for transmitting routing messages
# if nothing is configured. The interval can be overwritten
# globally at common.mcast_tx_interval or for each interface
# (e.g. some interfaces can handle more routing overhead, some
# link layer are overloaded with some bytes/second)
MCAST_TX_INTERVAL = 30

# don't recognize own mcast transmissions
# by default, can be changed for debugging
MCAST_LOOP = 1

# ident to drop all non-mdvrd applications.
IDENT = "MDVRD".encode('ascii')

# identify this sender
SECRET_COOKIE = str(uuid.uuid4())

# data compression level
ZIP_COMPRESSION_LEVEL = 9

ASYNC_IO_QUEUE_LENGTH = 32

# internal enum declarations start here:
# inter: HTTP IPC
TYPE_RTN_INTER_IPC = 1
# INTRA: mcast routing between mdvrd instances
TYPE_RTN_INTRA_IPC = 2

# exit codes for shell, failre cones can be sub-devided
# if required and shell/user has benefit of this information
EXIT_OK      = 0
EXIT_FAILURE = 1


def err(msg):
    sys.stderr.write(msg)
    sys.exit(EXIT_FAILURE)

def warn(msg):
    sys.stderr.write(msg)


def debug(msg):
    if not DEBUG_ON: return
    sys.stderr.write(msg)


def debugpp(d):
    if not DEBUG_ON: return
    pprint.pprint(d, indent=2, width=200, depth=6)
    sys.stderr.write("\n")


def msg(msg):
    sys.stdout.write(msg)


async def http_ipc_handle(request):
    queue_rt_proto = request.app['queue_rt_proto']
    request_data = addict.Dict(await request.json())
    msg = additct.Dict()
    msg.type = TYPE_RTN_INTER_IPC
    msg.data = request_data
    debugpp(request_data)
    try:
        fmt = "received route protcol message from {}:{}\n"
        debug(fmt.format( addr[0], addr[1]))
        queue_rt_proto.put_nowait(msg)
    except asyncio.queues.QueueFull:
        warn("queue overflow, strange things happens")

    response_data = {'status': 'ok'}
    body = json.dumps(response_data).encode('utf-8')
    return aiohttp.web.Response(body=body,
                                content_type="application/json")


def http_ipc_init(db, loop, queue_rt_proto):
    app = aiohttp.web.Application(loop=loop)
    app['queue_rt_proto'] = queue_rt_proto
    app['db'] = db
    app.router.add_route('POST', conf.ipc.path, http_ipc_handle)
    server = loop.create_server(app.make_handler(),
                                conf.ipc.v4_listen_addr,
                                conf.ipc.v4_listen_port)
    fmt = "HTTP IPC server started at http://{}:{}\n"
    msg(fmt.format(conf.ipc.v4_listen_addr, conf.ipc.v4_listen_port))
    loop.run_until_complete(server)


def rx_mcast_socket_init(conf):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    if hasattr(sock, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, MCAST_LOOP)

    sock.bind(('', int(conf.common.v4_mcast_port)))

    host = socket.inet_aton(socket.gethostbyname(socket.gethostname()))
    sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_IF, host)

    mcast_addr = socket.inet_aton(conf.common.v4_mcast_addr)
    mreq = struct.pack("4sl", mcast_addr, socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

    fmt = "Routing protocol mcast socket listen on {}:{}\n"
    msg(fmt.format(conf.common.v4_mcast_addr, conf.common.v4_mcast_port))

    return sock


def rx_mcast_socket_cb(fd, queue_rt_proto):
    try:
        data, addr = fd.recvfrom(2048)
    except socket.error as e:
        warn('Expection: {}'.format(e))
    d = addict.Dict()
    d.proto = "IPv4"
    d.data  = data
    d.src_addr = addr[0]
    d.src_port = addr[1]

    msg = addict.Dict()
    msg.type = TYPE_RTN_INTRA_IPC
    msg.data = d
    try:
        queue_rt_proto.put_nowait(msg)
        fmt = "received route protcol message from {}:{}\n"
        debug(fmt.format(addr[0], addr[1]))
    except asyncio.queues.QueueFull:
        warn("queue overflow, strange things happens")


def tx_socket_create(conf, out_addr):
    ttl = int(conf.common.mcast_tx_ttl)
    addr = socket.inet_aton(out_addr)
    sock = socket.socket(socket.AF_INET,
                         socket.SOCK_DGRAM,
                         socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, addr)
    return sock


def init_rx_tx_sockets(conf, db, loop, queue_rt_proto):
    fd = rx_mcast_socket_init(conf)
    partial_args = functools.partial(rx_mcast_socket_cb, fd, queue_rt_proto)
    loop.add_reader(fd, partial_args)
    for interface in conf.interfaces:
        addr = interface.local_v4_out_addr
        interface.local_v4_out_fd = tx_socket_create(conf, addr)
        db.interfaces.append(interface)


def rtn_rx_parse_payload_header(raw):
    if len(raw) < len(IDENT) + 4:
        # check for minimal length
        # ident(3) + size(>=4) + payload(>=1)
        warn("Header to short: {} byte".format(len(raw)))
        return False
    ident = raw[0:len(IDENT)]
    if ident != IDENT:
        print("ident wrong: expect:{} received:{}".format(IDENT, ident))
        return False
    return True


def rtn_rx_parse_payload_data(raw):
    size = struct.unpack('>I', raw[len(IDENT):len(IDENT) + 4])[0]
    if len(raw) < 7 + size:
        print("message seems corrupt")
        return False, None
    data = raw[len(IDENT) + 4:len(IDENT) + 4 + size]
    uncompressed_json = str(zlib.decompress(data), "utf-8")
    data = addict.Dict(json.loads(uncompressed_json))
    return True, data


def rtn_rx_msg_handler(conf, db, queue_msg):
    ok = rtn_rx_parse_payload_header(queue_msg.data.data)
    if not ok: return

    ok, data = rtn_rx_parse_payload_data(queue_msg.data.data)
    if not ok: return

    print("OK: {}".format(data))


def rtn_rx_msg_multiplex(conf, db, queue_msg):
    if queue_msg.type == TYPE_RTN_INTRA_IPC:
        rtn_rx_msg_handler(conf, db, queue_msg)
        pass
    elif queue_msg.type == TYPE_RTN_INTER_IPC:
        pass
    else:
        raise Exception("Internal error")


async def rtn_msg_handler(conf, db, queue_rt_proto):
    while True:
        queue_msg = await queue_rt_proto.get()
        rtn_rx_msg_multiplex(conf, db, queue_msg)


async def rtn_tx_block_for_work(conf, interface, timeout):
    try:
        await asyncio.wait_for(interface.queue_tx_ctrl.get(), timeout=timeout)
    except:
        pass


def rtn_tx_packet_create_body(conf):
    data = {}
    data["cookie"] = SECRET_COOKIE
    #create_payload_routing(conf, data)
    json_data = json.dumps(data)
    byte_stream = str.encode(json_data)
    compressed = zlib.compress(byte_stream, ZIP_COMPRESSION_LEVEL)
    crc32 = zlib.crc32(compressed) & 0xffffffff
    return compressed


def rtn_tx_packet_create_header(data_len):
    head = struct.pack('>I', data_len)
    return IDENT + head


def rtn_tx_packet_create(conf, db, interface):
    payload = rtn_tx_packet_create_body(conf)
    header = rtn_tx_packet_create_header(len(payload))
    return header + payload


def rtn_tx_send(conf, db, interface):
    addr = conf.common.v4_mcast_addr
    port = int(conf.common.v4_mcast_port)
    packet = rtn_tx_packet_create(conf, db, interface)

    fd = interface.local_v4_out_fd
    ret = fd.sendto(packet, (addr, port))
    debug("transmitted routing packet: {} bytes transmitted\n".format(ret))


async def rtn_tx_loop(conf, db, interface):
    timeout = 10
    if conf.common.mcast_tx_interval:
        timeout = conf.common.mcast_tx_interval
    if interface.mcast_tx_interval:
        timeout = interface.mcast_tx_interval
    while True:
        await rtn_tx_block_for_work(conf, interface, timeout)
        debug("send routing message via interface: {}\n".format(interface.local_v4_out_addr))
        rtn_tx_send(conf, db, interface)


def rtn_tx_tasks_init(conf, db):
    # we spawn a tx coroutine for every configured interface
    for interface in conf.interfaces:
        debug("Create coroutine for {}\n".format(interface.local_v4_out_addr))
        # create a new IPC queue to trigger a transmission
        # from outside the coroutine
        interface.queue_tx_ctrl = asyncio.Queue(ASYNC_IO_QUEUE_LENGTH)
        asyncio.ensure_future(rtn_tx_loop(conf, db, interface))


def db_init():
    db = addict.Dict()
    db.interfaces = []
    db.rtn_table = []
    return db


def main(conf):
    db = db_init()
    loop = asyncio.get_event_loop()
    queue_rt_proto = asyncio.Queue(ASYNC_IO_QUEUE_LENGTH)
    http_ipc_init(db, loop, queue_rt_proto)
    init_rx_tx_sockets(conf, db, loop, queue_rt_proto)
    asyncio.ensure_future(rtn_msg_handler(conf, db, queue_rt_proto))
    rtn_tx_tasks_init(conf, db)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        for task in asyncio.Task.all_tasks():
            task.cancel()
        loop.close()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--configuration", help="configuration", type=str, default=None)
    parser.add_argument("-v", "--verbose", help="verbose", action='store_true', default=False)
    args = parser.parse_args()
    if not args.configuration:
        err("Configuration required, please specify a valid file path, exiting now\n")
    return args


def load_configuration_file(args):
    with open(args.configuration) as json_data:
        return addict.Dict(json.load(json_data))


def init_global_behavior(args, conf):
    global DEBUG_ON
    if conf.common.debug or args.verbose:
        msg("Debug: enabled\n")
        DEBUG_ON = True
    else:
        msg("Debug: disabled\n")


def conf_init():
    args = parse_args()
    conf = load_configuration_file(args)
    init_global_behavior(args, conf)
    return conf


if __name__ == '__main__':
    msg("mdvrd - Multiline Distance Vector Routing Daemon, 2016\n")
    conf = conf_init()
    main(conf)
