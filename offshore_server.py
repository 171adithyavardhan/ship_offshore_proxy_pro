#!/usr/bin/env python3
"""
Offshore server that accepts the single persistent connection from the ship proxy.
Executes outbound HTTP(S) requests and tunnels CONNECT traffic.
"""
import asyncio
import json
import struct
import aiohttp

async def read_exact(reader, n):
    data = b""
    while len(data) < n:
        chunk = await reader.read(n - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return data

async def read_message(reader):
    hdr = await read_exact(reader, 4)
    (hlen,) = struct.unpack('>I', hdr)
    hjson = await read_exact(reader, hlen)
    header = json.loads(hjson.decode())
    body = b''
    if header.get('body_len', 0) > 0:
        body = await read_exact(reader, header['body_len'])
    return header, body

async def send_message(writer, header: dict, body: bytes = b''):
    hbytes = json.dumps(header).encode()
    writer.write(struct.pack('>I', len(hbytes)))
    writer.write(hbytes)
    if body:
        writer.write(body)
    await writer.drain()

class OffshoreServer:
    def __init__(self, host='0.0.0.0', port=9000):
        self.host = host
        self.port = port

    async def handle_ship(self, reader, writer):
        print("Ship connected")
        try:
            while True:
                header, body = await read_message(reader)
                mtype = header.get('type')

                if mtype == 'HTTPRequest':
                    await self._handle_http_request(writer, header, body)
                elif mtype == 'CONNECT':
                    await self._handle_connect(reader, writer, header)
                else:
                    print("Unknown message type", mtype)
        except Exception as e:
            print("ship disconnected", e)
            writer.close(); await writer.wait_closed()

    async def _handle_http_request(self, writer, header, body):
        method = header['method']
        url = header['url']
        print(f"⚓ Offshore: received HTTPRequest {method} {url} with {len(body)} bytes")
        if body:
            snippet = body[:100].decode(errors='replace')
            print(f"⚓ Offshore: body snippet: {snippet}")
        headers = header.get('headers', {})
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=headers, data=body) as resp:
                    rbody = await resp.read()
                    print(f"⚓ Offshore: sending HTTPResponse {resp.status} with {len(rbody)} bytes")
                    resp_header = {
                        'type': 'HTTPResponse',
                        'status_code': resp.status,
                        'headers': dict(resp.headers),
                        'body_len': len(rbody)
                    }
                    await send_message(writer, resp_header, rbody)
        except Exception as e:
            print("http request error", e)
            print("⚓ Offshore: sending HTTPResponse 502 Bad Gateway")
            resp_header = {
                'type': 'HTTPResponse',
                'status_code': 502,
                'headers': {'Content-Length': '11'},
                'body_len': 11
            }
            await send_message(writer, resp_header, b'Bad Gateway')

    async def _handle_connect(self, reader, writer, header):
        host = header['host']
        port = int(header['port'])
        print(f"⚓ Offshore: CONNECT to {host}:{port}")
        try:
            target_r, target_w = await asyncio.open_connection(host, port)
            await send_message(writer, {'type': 'CONNECT_OK'})

            async def ship_to_target():
                try:
                    while True:
                        h, b = await read_message(reader)
                        t = h.get('type')
                        if t == 'DATA':
                            if b:
                                target_w.write(b)
                                await target_w.drain()
                                print(f"⚓ Offshore: forwarded {len(b)} bytes ship→target")
                        elif t == 'DATA_END':
                            print("⚓ Offshore: ship finished sending data")
                            target_w.close()
                            await target_w.wait_closed()
                            break
                except Exception as e:
                    print(f"⚓ Offshore ship_to_target error: {e}")

            async def target_to_ship():
                try:
                    while True:
                        chunk = await target_r.read(1024)
                        print(f"⚓ Offshore: read {len(chunk)} bytes from target before sending")
                        if not chunk:
                            await send_message(writer, {'type': 'DATA_END', 'body_len': 0})
                            print("⚓ Offshore: target closed connection")
                            break
                        await send_message(writer, {'type': 'DATA', 'body_len': len(chunk)}, chunk)
                        print(f"⚓ Offshore: forwarded {len(chunk)} bytes target→ship")
                except Exception as e:
                    print(f"⚓ Offshore target_to_ship error: {e}")

            await asyncio.gather(ship_to_target(), target_to_ship())
        except Exception as e:
            print(f"⚓ Offshore CONNECT error: {e}")
            await send_message(writer, {'type': 'ERROR', 'message': str(e)})

    async def run(self):
        server = await asyncio.start_server(self.handle_ship, self.host, self.port)
        print(f"Offshore server listening on {self.host}:{self.port}")
        async with server:
            await server.serve_forever()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0', help='Offshore server host')
    parser.add_argument('--port', type=int, default=9000, help='Offshore server port')
    args = parser.parse_args()

    srv = OffshoreServer(host=args.host, port=args.port)
    asyncio.run(srv.run())