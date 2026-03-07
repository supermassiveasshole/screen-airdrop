# Deploy Legacy Sender on Python 3.7.6 Server

1. Upload the package wheel and dependency wheelhouse to the server.
2. Install offline:

```bash
python3.7 -m pip install --no-index --find-links ./wheelhouse screen-airdrop
```

3. Run sender:

```bash
screen-airdrop-sender-legacy /path/to/input --window-name "screen-airdrop"
```
