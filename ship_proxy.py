#!/usr/bin/env python3
"""
Ship-side proxy. Listens on :8080 for HTTP proxy requests (including CONNECT).
Maintains a single persistent connection to the offshore server and serializes requests.
"""
import asyncio
import json
import struct
import argparse

# framing helpers
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


class ShipProxy:
    def __init__(self, offshore_host, offshore_port, listen_host='0.0.0.0', listen_port=8080):
        self.offshore_host = offshore_host
        self.offshore_port = offshore_port
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.offshore_reader = None
        self.offshore_writer = None
        self.queue = asyncio.Queue()
        self._conn_lock = asyncio.Lock()  # ensures single persistent connection creation

    async def ensure_offshore(self):
        async with self._conn_lock:
            if self.offshore_writer and not self.offshore_writer.is_closing():
                return
            print('Connecting to offshore %s:%d' % (self.offshore_host, self.offshore_port))
            r, w = await asyncio.open_connection(self.offshore_host, self.offshore_port)
            self.offshore_reader = r
            self.offshore_writer = w
            print('Connected to offshore')

    async def handle_client(self, client_reader, client_writer):
        peer = client_writer.get_extra_info('peername')
        try:
            request_line = await client_reader.readline()
            if not request_line:
                client_writer.close(); await client_writer.wait_closed(); return
            # Example proxy request line: "GET http://example.com/path HTTP/1.1\r\n"
            first_line = request_line.decode().rstrip('\r\n')
            parts = first_line.split(' ')
            if len(parts) < 3:
                client_writer.close(); await client_writer.wait_closed(); return
            method, target, proto = parts[0], parts[1], parts[2]

            print(f"🚢 Ship: received client request: {first_line}")

            # Read headers
            headers = {}
            while True:
                line = await client_reader.readline()
                if not line or line == b'\r\n':
                    break
                ln = line.decode().rstrip('\r\n')
                if ':' in ln:
                    k, v = ln.split(':', 1)
                    headers[k.strip()] = v.strip()

            # Handle CONNECT specially
            if method.upper() == 'CONNECT':
                host, port = target.split(':') if ':' in target else (target, 443)
                await self.queue.put((self._handle_connect, (host, int(port), client_reader, client_writer)))
            else:
                # For normal HTTP proxy requests, we need to read any body if present (Content-Length)
                body = b''
                cl = int(headers.get('Content-Length') or 0)
                if cl > 0:
                    body = await read_exact(client_reader, cl)
                print(f"🚢 Ship: read {len(body)} bytes of request body")
                # push a task into queue
                await self.queue.put((self._handle_http_request, (method, target, headers, body, client_writer)))
        except Exception as e:
            print('client handler error', e)
            try:
                client_writer.close(); await client_writer.wait_closed()
            except: pass

    async def _worker(self):
        while True:
            task_func, args = await self.queue.get()
            print('🚢 Ship: worker picked up a task')
            try:
                await self.ensure_offshore()
                await task_func(*args)
            except Exception as e:
                print('task error', e)
            self.queue.task_done()

    async def _handle_http_request(self, method, target, headers, body, client_writer):
        print(f"🚢 Ship: sending HTTP request {method} {target} with {len(body)} bytes")
        header = {
            'type': 'HTTPRequest',
            'method': method,
            'url': target,
            'headers': headers,
            'body_len': len(body)
        }
        await send_message(self.offshore_writer, header, body)
        # read response
        try:
            resp_header, resp_body = await read_message(self.offshore_reader)
        except Exception as e:
            print('Error parsing offshore response:', e)
            client_writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 11\r\n\r\nBad Gateway')
            await client_writer.drain()
            client_writer.close(); await client_writer.wait_closed()
            return
        if resp_header.get('type') != 'HTTPResponse':
            # error
            client_writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 11\r\n\r\nBad Gateway')
            await client_writer.drain()
            client_writer.close(); await client_writer.wait_closed();
            return
        # send response back to client
        status = resp_header.get('status_code', 502)
        rhdrs = resp_header.get('headers', {})
        # status line
        client_writer.write(f'HTTP/1.1 {status} OK\r\n'.encode())
        for k,v in rhdrs.items():
            client_writer.write(f'{k}: {v}\r\n'.encode())
        client_writer.write(b'\r\n')
        if resp_body:
            client_writer.write(resp_body)
        await client_writer.drain()
        client_writer.close(); await client_writer.wait_closed()

    async def _handle_connect(self, host, port, client_reader, client_writer):
        # Send CONNECT header to offshore and wait for CONNECT_OK
        header = {'type': 'CONNECT', 'host': host, 'port': port}
        await send_message(self.offshore_writer, header, b'')
        ok_header, _ = await read_message(self.offshore_reader)
        if ok_header.get('type') != 'CONNECT_OK':
            client_writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 11\r\n\r\nBad Gateway')
            await client_writer.drain(); client_writer.close(); await client_writer.wait_closed();
            return
        # Reply 200 to client
        client_writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await client_writer.drain()

        # Now enter loop forwarding data: read from client, send DATA frames; read from offshore for DATA frames and write to client.
        async def read_client_send():
            try:
                while True:
                    chunk = await client_reader.read(4096)
                    if not chunk:
                        # send DATA_END with explicit 0 length
                        await send_message(self.offshore_writer, {'type': 'DATA_END', 'body_len': 0}, b'')
                        print('🚢 Ship: client->offshore DATA_END sent')
                        break
                    # send DATA with body_len so offshore will read the body correctly
                    await send_message(self.offshore_writer, {'type': 'DATA', 'body_len': len(chunk)}, chunk)
                    print(f"🚢 Ship: forwarded {len(chunk)} bytes client->offshore")
            except Exception as e:
                print('read_client_send', e)
                try:
                    await send_message(self.offshore_writer, {'type': 'DATA_END', 'body_len': 0}, b'')
                except: pass

        async def read_offshore_write():
            try:
                while True:
                    h, b = await read_message(self.offshore_reader)
                    t = h.get('type')
                    print(f"🚢 Ship: received frame type {t}")
                    if t == 'DATA':
                        print(f"🚢 Ship: received {len(b)} bytes from offshore")
                        if b:
                            client_writer.write(b)
                            await client_writer.drain()
                    elif t == 'DATA_END':
                        print("🚢 Ship: received DATA_END")
                        break
                    else:
                        print(f"🚢 Ship: received unexpected frame type {t}")
            except Exception as e:
                print('read_offshore_write', e)

        await asyncio.gather(read_client_send(), read_offshore_write())
        try:
            client_writer.close(); await client_writer.wait_closed()
        except: pass

    async def run(self):
        server = await asyncio.start_server(self.handle_client, host=self.listen_host, port=self.listen_port)
        print('Ship proxy listening on %s:%d' % (self.listen_host, self.listen_port))
        worker = asyncio.create_task(self._worker())
        async with server:
            await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--offshore-host', default='127.0.0.1')
    parser.add_argument('--offshore-port', type=int, default=9000)
    parser.add_argument('--listen-port', type=int, default=8080)
    args = parser.parse_args()
    sp = ShipProxy(args.offshore_host, args.offshore_port, listen_port=args.listen_port)
    asyncio.run(sp.run())
