#!/bin/bash

# MCP Remote Machine Server Installation Script
set -e

echo "Installing MCP Remote Machine Control Server..."

# Check Python version
if ! python3 --version | grep -E "3\.(8|9|10|11|12)" > /dev/null; then
    echo "Error: Python 3.8+ required"
    exit 1
fi

# Install dependencies
echo "Installing Python dependencies..."
pip3 install --user -r requirements.txt

# Make server executable
chmod +x remote_machine_server.py

# Get current directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installation Complete ==="
echo ""
echo "Server installed at: $SCRIPT_DIR/remote_machine_server.py"
echo ""
echo "Usage Options:"
echo ""
echo "1. STDIO Mode (for Claude Code local use):"
echo "   python3 $SCRIPT_DIR/remote_machine_server.py --transport stdio"
echo ""
echo "2. SSE Mode (for network access):"
echo "   python3 $SCRIPT_DIR/remote_machine_server.py --transport sse --host 0.0.0.0 --port 8765"
echo ""
echo "3. Configure Claude Code:"
echo "   claude mcp add remote-machine \"python3 $SCRIPT_DIR/remote_machine_server.py --transport stdio\""
echo ""
echo "4. Test the server:"
echo "   echo '{\"jsonrpc\":\"2.0\",\"method\":\"system_info\",\"params\":{},\"id\":1}' | python3 $SCRIPT_DIR/remote_machine_server.py"
echo ""
echo "Security Notes:"
echo "- Use authenticate_sudo tool before running privileged commands"
echo "- Sudo authentication is cached for 30 minutes per session"
echo "- For network access, ensure firewall allows connections on chosen port"