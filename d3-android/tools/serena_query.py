"""Query the local Serena MCP server without requiring client registration."""
import json
import sys
import requests

sys.stdout.reconfigure(encoding="utf-8")

URL = "http://127.0.0.1:9144/mcp"
headers = {"Accept": "application/json, text/event-stream"}


def rpc(method, params, ident=1):
    payload = {"jsonrpc": "2.0", "method": method, "params": params}
    if ident is not None:
        payload["id"] = ident
    response = requests.post(URL, headers=headers, json=payload, timeout=180)
    response.raise_for_status()
    if "Mcp-Session-Id" in response.headers:
        headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
    if not response.text:
        return {}
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return json.loads(next(line[6:] for line in response.text.splitlines() if line.startswith("data: ")))
    return response.json()


rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "d3-symbol-query", "version": "1"}})
rpc("notifications/initialized", {}, None)
if sys.argv[1] == "list":
    result = rpc("tools/list", {})
elif sys.argv[1] == "batch":
    for query in json.loads(sys.argv[2]):
        result = rpc("tools/call", query)["result"]
        print(query["arguments"].get("name_path_pattern", query["name"]))
        print(result.get("structuredContent", {}).get("result", result.get("content")))
    sys.exit(0)
else:
    result = rpc("tools/call", {"name": sys.argv[1], "arguments": json.loads(sys.argv[2])})
result = result.get("result", result)
print(result.get("structuredContent", {}).get("result", json.dumps(result, ensure_ascii=False)))
