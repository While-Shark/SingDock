#!/usr/bin/env python3
"""Create an isolated smoke-test client using the server's persisted identity."""
import json
import os
from pathlib import Path
import socket
import ssl
import sys


def client_config(config, tag, credentials=None):
    inbound = next(item for item in config["inbounds"] if item["tag"] == tag)
    outbound = {
        "type": inbound["type"],
        "tag": "proxy",
        "server": "127.0.0.1",
        "server_port": inbound["listen_port"],
    }
    kind = inbound["type"]
    if kind == "shadowsocks":
        outbound.update(method=inbound["method"], password=inbound["password"])
    elif kind == "vmess":
        outbound.update(uuid=inbound["users"][0]["uuid"], security="auto")
        outbound["transport"] = inbound["transport"]
    elif kind in ("vless", "trojan"):
        user = inbound["users"][0]
        if kind == "vless":
            outbound["uuid"] = user["uuid"]
            if "flow" in user:
                outbound["flow"] = user["flow"]
        else:
            outbound["password"] = user["password"]
        if "transport" in inbound:
            outbound["transport"] = inbound["transport"]
        outbound["tls"] = {
            "enabled": True,
            "server_name": inbound["tls"]["server_name"],
            "utls": {"enabled": True, "fingerprint": "chrome"},
            "reality": {
                "enabled": True,
                "public_key": credentials["REALITY_PUB"],
                "short_id": inbound["tls"]["reality"]["short_id"][0],
            },
        }
    elif kind in ("hysteria2", "tuic", "anytls"):
        outbound["password"] = inbound["users"][0]["password"]
        if kind == "tuic":
            outbound["uuid"] = inbound["users"][0]["uuid"]
            outbound["congestion_control"] = inbound["congestion_control"]
        if "obfs" in inbound:
            outbound["obfs"] = inbound["obfs"]
        tls = inbound["tls"]
        # Trust the generated certificate explicitly; keep verification enabled.
        certificate = ssl._ssl._test_decode_cert(tls["certificate_path"])
        server_name = next(
            value for kind, value in certificate["subjectAltName"] if kind == "DNS"
        )
        outbound["tls"] = {
            "enabled": True,
            "server_name": server_name,
            "certificate_path": tls["certificate_path"],
        }
        if "alpn" in tls:
            outbound["tls"]["alpn"] = tls["alpn"]
    else:
        raise ValueError(f"Unsupported smoke-test protocol: {kind}")

    # A mixed inbound uses TCP and UDP on the same port.
    for _ in range(32):
        with socket.socket() as listener, socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM
        ) as datagram:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            try:
                datagram.bind(("127.0.0.1", port))
            except OSError:
                continue
            break
    else:
        raise RuntimeError("No free local TCP+UDP client port")
    return {
        "inbounds": [{"type": "mixed", "listen": "127.0.0.1", "listen_port": port}],
        "outbounds": [outbound],
        "dns": {"servers": [{"type": "local", "tag": "dns-local"}]},
        "route": {"final": "proxy", "default_domain_resolver": "dns-local"},
    }, port


def main():
    source, tag, destination = sys.argv[1:]
    credentials = dict(
        line.split("=", 1)
        for line in (Path(source).parent / "creds.env").read_text().splitlines()
        if "=" in line
    )
    config, port = client_config(json.loads(Path(source).read_text()), tag, credentials)
    # Test files contain real node credentials; never print their contents.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(config, output)
    print(port)


if __name__ == "__main__":
    main()
