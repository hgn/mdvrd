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

DEBUG_ON = False


def err(msg):
    sys.stderr.write(msg)
    sys.exit(1)


def debug(msg):
    if not DEBUG_ON: return
    sys.stderr.write(msg)


def debugpp(d):
    if not DEBUG_ON: return
    pprint.pprint(d, indent=2, width=200, depth=6)
    sys.stderr.write("\n")


def msg(msg):
    sys.stdout.write(msg)


async def handle(request):
    data = addict.Dict(await request.json())
    debugpp(data)
    response_data = {'status': 'ok'}
    body = json.dumps(response_data).encode('utf-8')
    return aiohttp.web.Response(body=body, content_type="application/json")


def main(conf):
    loop = asyncio.get_event_loop()
    app = aiohttp.web.Application(loop=loop)
    app.router.add_route('POST', conf.ipc.path, handle)

    server = loop.create_server(app.make_handler(), conf.ipc.v4_listen_addr, conf.ipc.v4_listen_port)
    msg("Server started at http://{}:{}\n".format(conf.ipc.v4_listen_addr, conf.ipc.v4_listen_port))
    loop.run_until_complete(server)
    try:
       loop.run_forever()
    except KeyboardInterrupt:
       pass


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configuration", help="configuration", type=str, default=None)
    args = parser.parse_args()
    if not args.configuration:
        err("Configuration required, please specify a valid file path, exiting now\n")
    return args


def load_configuration_file(args):
    with open(args.configuration) as json_data:
        return addict.Dict(json.load(json_data))

def init_global_behave(conf):
    if conf.common.debug == "verbose":
        DEBUG_ON = True

def conf_init():
    args = parse_args()
    conf = load_configuration_file(args)
    init_global_behave(conf)
    return conf


if __name__ == '__main__':
    conf = conf_init()
    main(conf)
