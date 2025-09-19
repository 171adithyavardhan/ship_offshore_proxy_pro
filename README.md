

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


## Test Run Screenshots

Below are the screenshots of all successful tests demonstrating the project functionality:

### 1️⃣ Handling Non-Existent Domain
![Nonexistent Domain Test](./screenshots/Screenshot%202025-09-20%20at%2000.51.07.png)

### 2️⃣ HTTP POST Request to httpbin
![POST Request](./screenshots/Screenshot%202025-09-20%20at%2000.51.10.png)

### 3️⃣ Large Data Transfer & Proxy Tunnel
![Large Data Transfer](./screenshots/Screenshot%202025-09-20%20at%2000.51.15.png)

### 4️⃣ CONNECT Tunnel to Example.com
![HTTPS CONNECT](./screenshots/Screenshot%202025-09-20%20at%2000.52.31.png)

### 5️⃣ Speed Test via Proxy (Hetzner 1MB)
![Speed Test](./screenshots/Screenshot%202025-09-20%20at%2000.53.04.png)

### 6️⃣ Successful POST Result (Detailed Output)
![POST Result](./screenshots/Screenshot%202025-09-20%20at%2000.53.09.png)

### 7️⃣ Offshore Server Forwarding & Logging
![Offshore Logging](./screenshots/Screenshot%202025-09-20%20at%2000.53.22.png)

### 8️⃣ SSL Handshake with Example.com
![SSL Handshake](./screenshots/Screenshot%202025-09-20%20at%2000.54.12.png)

### 9️⃣ Final Test Output
![Final Output](./screenshots/Screenshot%202025-09-20%20at%2000.54.31.png)

### 🔟 Additional Logs
![Additional Logs](./screenshots/Screenshot%202025-09-20%20at%2000.54.37.png)
Then test as above.
