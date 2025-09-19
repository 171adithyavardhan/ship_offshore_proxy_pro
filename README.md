

# Ship-Offshore Single-Connection Proxy

## Run locally without Docker
1. Start offshore:
   ```bash
   python3 offshore_server.py
   ```
2. In another terminal, start ship:
   ```bash
   python3 ship_proxy.py --offshore-host 127.0.0.1 --offshore-port 9000
   ```
3. Test:
   ```bash
   curl -x http://localhost:8080 http://httpforever.com/
   ```

## Run with Docker Compose
```bash
docker-compose up --build
```

Then test as above.