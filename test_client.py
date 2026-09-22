import asyncio
import base64
import hashlib
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp.client.session import ClientSession

SERVER_URL = "http://localhost:8000"
CLIENT_ID = "test-script-client"
CALLBACK_PORT = 8080
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"

auth_code = None

class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress logging
        
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html><body>
                    <h1 style="color: green">Authorization Successful!</h1>
                    <p>You can close this window now and check your terminal.</p>
                </body></html>
            """)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing code in callback.")

def run_callback_server():
    server = HTTPServer(('localhost', CALLBACK_PORT), CallbackHandler)
    while auth_code is None:
        server.handle_request()

async def main():
    print("=" * 60)
    print(" VERISTEAD MCP OAUTH 2.1 PKCE TEST CLIENT")
    print("=" * 60)
    
    # 1. Generate PKCE values (S256)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('ascii')).digest()
    ).decode('ascii').rstrip('=')

    # 2. Start callback server in background thread to catch the GitHub redirect
    server_thread = threading.Thread(target=run_callback_server, daemon=True)
    server_thread.start()

    # 3. Construct Authorization URL
    auth_url = (
        f"{SERVER_URL}/auth/authorize?"
        f"response_type=code&"
        f"client_id={CLIENT_ID}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"code_challenge={code_challenge}&"
        f"code_challenge_method=S256&"
        f"scope=user"
    )
                
    print("\n👉 ACTION REQUIRED: Open this URL in your browser to log in via GitHub:")
    print(f"\n{auth_url}\n")
    print("Waiting for browser redirect...")

    # Wait for the user to complete login flow
    while auth_code is None:
        await asyncio.sleep(0.5)

    print(f"\n✅ Received Authorization Code: {auth_code[:8]}........")

    # 4. Token Exchange
    print(f"🔄 Exchanging code for Bearer token...")
    token_url = f"{SERVER_URL}/auth/token"
    token_data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=token_data)
        
    if resp.status_code != 200:
        print("❌ Token exchange failed!")
        print(resp.text)
        return
        
    access_token = resp.json().get("access_token")
    print("✅ Success! Obtained Access Token.")
    
    # 5. Connect to MCP Server via SSE using the token and call a tool
    mcp_endpoint = f"{SERVER_URL}/mcp/"
    print(f"\n🚀 Connecting to FastMCP Secure Stream at {mcp_endpoint} ...")
    
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        async with streamable_http_client(mcp_endpoint, headers=headers) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("✅ MCP Session Initialized.")
                
                print("\nFetching available tools...")
                tools_response = await session.list_tools()
                print(f"Tools available: {', '.join(t.name for t in tools_response.tools)}")
                
                print("\nExecuting 'get_device_status' tool securely...")
                result = await session.call_tool("get_device_status", {})
                
                print("\n" + "=" * 60)
                print(" SECURE TOOL EXECUTION RESULT:")
                print("=" * 60)
                for item in result.content:
                    print(item.text)
                print("=" * 60)
                
    except Exception as e:
        print(f"\n❌ MCP Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
