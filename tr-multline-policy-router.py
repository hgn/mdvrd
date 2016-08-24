#!/usr/bin/env python3

import asyncio
import aiohttp.web

async def handle(request):
    response_data = {'status': 'ok'}
    body = json.dumps(response_data).encode('utf-8')
    return aiohttp.web.Response(body=body, content_type="application/json")

def main():
    loop = asyncio.get_event_loop()
    app = aiohttp.web.Application(loop=loop)
    app.router.add_route('GET', '/', handle)

    server = loop.create_server(app.make_handler(), '127.0.0.1', 50000)
    print("Server started at http://127.0.0.1:8000")
    loop.run_until_complete(server)
    try:
       loop.run_forever()
    except KeyboardInterrupt:
       pass

if __name__ == '__main__':
   main()
