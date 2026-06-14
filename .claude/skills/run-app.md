# run-app — taxmanager local dev server

Starts the taxmanager single-file app on localhost:8787.

## Start

```bash
pkill -f "python3 -m http.server 8787" 2>/dev/null; true
cd /home/user/taxmanager && python3 -m http.server 8787 &>/tmp/taxmanager-server.log &
sleep 1
curl -s -o /dev/null -w "%{http_code}" http://localhost:8787/
```

Expected output: `200`

## Stop

```bash
pkill -f "python3 -m http.server 8787" 2>/dev/null; true
```

## Logs

```bash
cat /tmp/taxmanager-server.log
```
