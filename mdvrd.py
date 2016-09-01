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

# default false, can be changed via program arguments (-v)
DEBUG_ON = False

# don't recognize own mcast transmissions
# by default, can be changed for debugging
MCAST_LOOP = 0

ASYNC_IO_QUEUE_LENGTH = 32

# internal enum declarations start here:
# inter: HTTP IPC
TYPE_RTN_INTER_IPC = 1
# INTRA: mcast routing between mdvrd instances
TYPE_RTN_INTRA_IPC = 2


def err(msg):
    sys.stderr.write(msg)
    sys.exit(1)

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
        queue_rt_proto.put_nowait(msg)
        debug("received route protcol message from {}:{}\n".format(addr[0], addr[1]))
    except asyncio.queues.QueueFull:
        warn("queue overflow, strange things happens")

    response_data = {'status': 'ok'}
    body = json.dumps(response_data).encode('utf-8')
    return aiohttp.web.Response(body=body, content_type="application/json")


def http_ipc_init(db, loop, queue_rt_proto):
    app = aiohttp.web.Application(loop=loop)
    app['queue_rt_proto'] = queue_rt_proto
    app['db'] = db
    app.router.add_route('POST', conf.ipc.path, http_ipc_handle)

    server = loop.create_server(app.make_handler(), conf.ipc.v4_listen_addr, conf.ipc.v4_listen_port)
    msg("HTTP IPC server started at http://{}:{}\n".format(conf.ipc.v4_listen_addr, conf.ipc.v4_listen_port))
    loop.run_until_complete(server)


def rx_mcast_socket_init(conf):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(sock, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, MCAST_LOOP)

    sock.bind(('', int(conf.common.v4_listen_port)))
    host = socket.gethostbyname(socket.gethostname())
    sock.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_IF, socket.inet_aton(host))

    mreq = struct.pack("4sl", socket.inet_aton(conf.common.v4_mcast_addr), socket.INADDR_ANY)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    msg("Routing protocol mcast socket listen on {}:{}\n".format(conf.common.v4_mcast_addr, conf.common.v4_listen_port))
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
        debug("received route protcol message from {}:{}\n".format(addr[0], addr[1]))
    except asyncio.queues.QueueFull:
        warn("queue overflow, strange things happens")

def tx_socket_create(conf, out_addr):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, int(conf.common.mcast_tx_ttl))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(out_addr))
    return sock


def init_rx_tx_sockets(conf, db, loop, queue_rt_proto):
    fd = rx_mcast_socket_init(conf)
    loop.add_reader(fd, functools.partial(rx_mcast_socket_cb, fd, queue_rt_proto))
    for interface in conf.interfaces:
        interface.local_v4_out_fd = tx_socket_create(conf, interface.local_v4_out_addr)
        db.interfaces.append(interface)


def rtn_rx_msg_multiplex(data):
    if data.type == TYPE_RTN_INTRA_IPC:
        pass
    elif data.type == TYPE_RTN_INTER_IPC:
        pass
    else:
        raise Exception("Internal error")


async def rtn_msg_handler(conf, db, queue_rt_proto):
    while True:
        entry = await queue_rt_proto.get()
        rtn_rx_msg_multiplex(entry)


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
    if conf.common.debug == "verbose" or args.verbose:
        DEBUG_ON = True


def conf_init():
    args = parse_args()
    conf = load_configuration_file(args)
    init_global_behavior(args, conf)
    return conf


if __name__ == '__main__':
    conf = conf_init()
    main(conf)
