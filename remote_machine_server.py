#!/usr/bin/env python3
"""
MCP Server for Remote Machine Control
Provides comprehensive system control capabilities through MCP protocol.
"""

import asyncio
import json
import logging
import os
import platform
import psutil
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import getpass
import socket

from mcp.server.fastmcp import FastMCP
from mcp.server.stdio import stdio_server
from mcp.server.sse import sse_server
from mcp.types import TextContent, ImageContent, EmbeddedResource


class SudoManager:
    def __init__(self, timeout_minutes: int = 30):
        self.password: Optional[str] = None
        self.last_auth: Optional[datetime] = None
        self.timeout_minutes = timeout_minutes
    
    def is_authenticated(self) -> bool:
        if not self.password or not self.last_auth:
            return False
        return datetime.now() - self.last_auth < timedelta(minutes=self.timeout_minutes)
    
    def authenticate(self, password: str) -> bool:
        """Test sudo password and cache if valid"""
        try:
            proc = subprocess.run(
                ['sudo', '-S', 'true'],
                input=f"{password}\n",
                text=True,
                capture_output=True,
                timeout=5
            )
            if proc.returncode == 0:
                self.password = password
                self.last_auth = datetime.now()
                return True
        except subprocess.TimeoutExpired:
            pass
        return False
    
    def run_with_sudo(self, command: List[str]) -> subprocess.CompletedProcess:
        """Execute command with sudo using cached password"""
        if not self.is_authenticated():
            raise Exception("Sudo authentication required or expired")
        
        sudo_cmd = ['sudo', '-S'] + command
        return subprocess.run(
            sudo_cmd,
            input=f"{self.password}\n",
            text=True,
            capture_output=True
        )


# Initialize server
mcp = FastMCP("Remote Machine Controller")
sudo_manager = SudoManager()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@mcp.tool()
def authenticate_sudo(password: str) -> str:
    """Authenticate sudo access with password (cached for session)"""
    if sudo_manager.authenticate(password):
        return "Sudo authentication successful. Access cached for 30 minutes."
    return "Sudo authentication failed. Please check password."


@mcp.tool()
def execute_command(command: str, use_sudo: bool = False, working_dir: str = None) -> Dict[str, Any]:
    """Execute shell command with optional sudo"""
    try:
        if use_sudo and not sudo_manager.is_authenticated():
            return {"error": "Sudo authentication required. Use authenticate_sudo first."}
        
        if use_sudo:
            result = sudo_manager.run_with_sudo(['sh', '-c', command])
        else:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=working_dir
            )
        
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "success": result.returncode == 0
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def read_file(file_path: str, max_lines: int = 1000) -> Dict[str, Any]:
    """Read file contents with line limit"""
    try:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}
        
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append(f"... (truncated at {max_lines} lines)")
                    break
                lines.append(line.rstrip())
        
        return {
            "content": "\n".join(lines),
            "size": path.stat().st_size,
            "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def write_file(file_path: str, content: str, backup: bool = True) -> Dict[str, Any]:
    """Write content to file with optional backup"""
    try:
        path = Path(file_path)
        
        # Create backup if file exists
        if backup and path.exists():
            backup_path = f"{file_path}.backup.{int(time.time())}"
            shutil.copy2(path, backup_path)
        
        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return {
            "success": True,
            "bytes_written": len(content.encode('utf-8')),
            "backup_created": backup and path.exists()
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_directory(directory: str = ".", show_hidden: bool = False) -> Dict[str, Any]:
    """List directory contents with file info"""
    try:
        path = Path(directory)
        if not path.exists():
            return {"error": f"Directory not found: {directory}"}
        
        items = []
        for item in path.iterdir():
            if not show_hidden and item.name.startswith('.'):
                continue
            
            stat = item.stat()
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "permissions": oct(stat.st_mode)[-3:]
            })
        
        return {
            "path": str(path.absolute()),
            "items": sorted(items, key=lambda x: (x["type"] != "directory", x["name"]))
        }
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def file_operations(operation: str, source: str, destination: str = None, recursive: bool = False) -> Dict[str, Any]:
    """Perform file operations: copy, move, delete, chmod, chown"""
    try:
        src_path = Path(source)
        
        if operation == "delete":
            if src_path.is_dir():
                shutil.rmtree(src_path)
            else:
                src_path.unlink()
            return {"success": True, "message": f"Deleted {source}"}
        
        elif operation == "copy" and destination:
            dest_path = Path(destination)
            if src_path.is_dir():
                shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dest_path)
            return {"success": True, "message": f"Copied {source} to {destination}"}
        
        elif operation == "move" and destination:
            shutil.move(source, destination)
            return {"success": True, "message": f"Moved {source} to {destination}"}
        
        else:
            return {"error": f"Unsupported operation or missing destination: {operation}"}
    
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def process_management(action: str, process_identifier: str = None, signal: str = "TERM") -> Dict[str, Any]:
    """Manage processes: list, kill, info"""
    try:
        if action == "list":
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
                try:
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return {"processes": processes[:50]}  # Limit to 50 processes
        
        elif action == "kill" and process_identifier:
            try:
                pid = int(process_identifier)
                proc = psutil.Process(pid)
                proc.terminate()
                return {"success": True, "message": f"Terminated process {pid}"}
            except ValueError:
                # Kill by name
                killed = 0
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['name'] == process_identifier:
                        proc.terminate()
                        killed += 1
                return {"success": True, "message": f"Terminated {killed} processes named {process_identifier}"}
        
        elif action == "info" and process_identifier:
            pid = int(process_identifier)
            proc = psutil.Process(pid)
            return {
                "pid": proc.pid,
                "name": proc.name(),
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(),
                "memory_percent": proc.memory_percent(),
                "create_time": datetime.fromtimestamp(proc.create_time()).isoformat()
            }
    
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def service_control(action: str, service_name: str) -> Dict[str, Any]:
    """Control systemd services: start, stop, restart, enable, disable, status"""
    try:
        if not sudo_manager.is_authenticated():
            return {"error": "Sudo authentication required for service control"}
        
        valid_actions = ["start", "stop", "restart", "enable", "disable", "status"]
        if action not in valid_actions:
            return {"error": f"Invalid action. Use: {', '.join(valid_actions)}"}
        
        if action == "status":
            result = subprocess.run(
                ["systemctl", "status", service_name],
                capture_output=True,
                text=True
            )
        else:
            result = sudo_manager.run_with_sudo(["systemctl", action, service_name])
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.stderr else None
        }
    
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def package_management(action: str, package_name: str = None) -> Dict[str, Any]:
    """Manage packages: install, remove, update, list, search"""
    try:
        if not sudo_manager.is_authenticated() and action in ["install", "remove", "update"]:
            return {"error": "Sudo authentication required for package management"}
        
        # Detect package manager
        pkg_managers = {
            "apt": ["apt", "apt-get"],
            "yum": ["yum"],
            "dnf": ["dnf"],
            "pacman": ["pacman"],
            "zypper": ["zypper"]
        }
        
        pkg_cmd = None
        for manager, commands in pkg_managers.items():
            for cmd in commands:
                if shutil.which(cmd):
                    pkg_cmd = cmd
                    break
            if pkg_cmd:
                break
        
        if not pkg_cmd:
            return {"error": "No supported package manager found"}
        
        # Build command
        if pkg_cmd in ["apt", "apt-get"]:
            cmd_map = {
                "install": [pkg_cmd, "install", "-y", package_name],
                "remove": [pkg_cmd, "remove", "-y", package_name],
                "update": [pkg_cmd, "update"],
                "search": [pkg_cmd, "search", package_name],
                "list": [pkg_cmd, "list", "--installed"]
            }
        elif pkg_cmd == "pacman":
            cmd_map = {
                "install": [pkg_cmd, "-S", "--noconfirm", package_name],
                "remove": [pkg_cmd, "-R", package_name],
                "update": [pkg_cmd, "-Syu", "--noconfirm"],
                "search": [pkg_cmd, "-Ss", package_name],
                "list": [pkg_cmd, "-Q"]
            }
        else:
            return {"error": f"Package manager {pkg_cmd} not fully supported yet"}
        
        if action not in cmd_map:
            return {"error": f"Action {action} not supported"}
        
        if action in ["install", "remove", "update"]:
            result = sudo_manager.run_with_sudo(cmd_map[action])
        else:
            result = subprocess.run(cmd_map[action], capture_output=True, text=True)
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout[:2000],  # Limit output
            "error": result.stderr if result.stderr else None
        }
    
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def system_info() -> Dict[str, Any]:
    """Get comprehensive system information"""
    try:
        # CPU info
        cpu_info = {
            "cores": psutil.cpu_count(),
            "usage_percent": psutil.cpu_percent(interval=1),
            "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else None
        }
        
        # Memory info
        memory = psutil.virtual_memory()
        memory_info = {
            "total_gb": round(memory.total / (1024**3), 2),
            "available_gb": round(memory.available / (1024**3), 2),
            "usage_percent": memory.percent
        }
        
        # Disk info
        disk_info = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "usage_percent": round((usage.used / usage.total) * 100, 1)
                })
            except PermissionError:
                continue
        
        # Network info
        network_info = []
        for interface, addresses in psutil.net_if_addrs().items():
            for addr in addresses:
                if addr.family == socket.AF_INET:
                    network_info.append({
                        "interface": interface,
                        "ip": addr.address,
                        "netmask": addr.netmask
                    })
        
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "uptime_seconds": time.time() - psutil.boot_time(),
            "cpu": cpu_info,
            "memory": memory_info,
            "disk": disk_info,
            "network": network_info
        }
    
    except Exception as e:
        return {"error": str(e)}


async def main():
    """Main server entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Remote Machine Control Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                       help="Transport type (default: stdio)")
    parser.add_argument("--host", default="localhost", help="Host for SSE transport")
    parser.add_argument("--port", type=int, default=8765, help="Port for SSE transport")
    args = parser.parse_args()
    
    if args.transport == "stdio":
        async with stdio_server() as (read_stream, write_stream):
            await mcp.run(read_stream, write_stream, mcp.create_initialization_options())
    
    elif args.transport == "sse":
        async with sse_server(host=args.host, port=args.port) as server:
            logger.info(f"MCP Server running on http://{args.host}:{args.port}")
            await server.serve(mcp)


if __name__ == "__main__":
    asyncio.run(main())