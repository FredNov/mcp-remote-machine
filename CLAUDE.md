# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Architecture

This is an MCP (Model Context Protocol) server that provides comprehensive system control capabilities for Claude Code. The architecture consists of:

- **`remote_machine_server.py`**: Main MCP server using FastMCP framework with 12 system control tools
- **`SudoManager` class**: Session-based sudo authentication with 30-minute password caching
- **Transport modes**: STDIO (for local/SSH) and SSE (for network access)
- **Tool categories**: File operations, process management, service control, package management, system monitoring, command execution

## Development Commands

### Installation and Setup
```bash
# Install dependencies and setup server
./install_server.sh

# Manual dependency installation
pip3 install --user -r requirements.txt

# Make server executable
chmod +x remote_machine_server.py
```

### Running the Server

**STDIO Mode** (recommended for local/SSH):
```bash
python3 remote_machine_server.py --transport stdio
```

**SSE Mode** (for network access):
```bash
python3 remote_machine_server.py --transport sse --host 0.0.0.0 --port 8765
```

### Testing
```bash
# Test server with system_info call
echo '{"jsonrpc":"2.0","method":"system_info","params":{},"id":1}' | python3 remote_machine_server.py --transport stdio

# Test individual tools (requires MCP client)
# authenticate_sudo, execute_command, read_file, write_file, list_directory, 
# file_operations, process_management, service_control, package_management, system_info
```

### Claude Code Integration
```bash
# Add MCP server to Claude Code
claude mcp add remote-machine "python3 /path/to/remote_machine_server.py --transport stdio"

# For network access
claude mcp add remote-machine-net "python3 /path/to/remote_machine_server.py --transport sse --host 0.0.0.0 --port 8765"
```

## Key Implementation Details

### Authentication Flow
1. Initial sudo authentication via `authenticate_sudo(password)` tool
2. Password cached in memory for 30 minutes (configurable via `SudoManager.timeout_minutes`)
3. All privileged operations check `sudo_manager.is_authenticated()` before execution
4. Passwords never stored persistently - only in memory during session

### Tool Structure
All tools return structured dictionaries with:
- Success operations: `{"success": True, "data": {...}}`
- Error conditions: `{"error": "description"}`
- Command execution: `{"stdout": "...", "stderr": "...", "returncode": int, "success": bool}`

### Package Manager Detection
Auto-detects available package managers in order: apt/apt-get, yum, dnf, pacman, zypper
Commands are dynamically built based on detected manager.

### Security Considerations
- Server designed for local network use
- Sudo passwords cached in memory only
- Session timeout prevents indefinite access
- All privileged operations require prior authentication
- Command audit logging via Python logging framework