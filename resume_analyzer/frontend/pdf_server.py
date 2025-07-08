import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional
import time
import signal
import urllib.parse

class PDFServer:
    def __init__(self, base_dir: str = "/tmp/pdf_storage", port: int = 8085):
        print(f"🚀 Initializing PDF Server...")
        self.base_dir = Path(base_dir)
        self.port = port
        
        # Use the network IP instead of localhost
        self.base_url = f"http://192.168.1.172:{port}"
        self.server_process = None
        
        print(f"📁 Base directory: {self.base_dir}")
        print(f"🌐 Base URL: {self.base_url}")
        
        # Create base directory if it doesn't exist
        self.base_dir.mkdir(exist_ok=True)
        print(f"✅ Base directory created/verified: {self.base_dir}")
        
        # Start the server
        self.start_server()
    
    def start_server(self):
        """Start the HTTP server using Python's built-in server"""
        try:
            print(f"🔧 Starting PDF server on port {self.port}...")
            
            # Kill any existing server on this port
            self.stop_server()
            
            # Wait a moment after stopping
            time.sleep(1)
            
            # Use Python's built-in HTTP server - bind to all interfaces
            cmd = [
                "python3", "-m", "http.server", str(self.port),
                "--directory", str(self.base_dir),
                "--bind", "0.0.0.0"
            ]
            
            print(f"🔧 Running command: {' '.join(cmd)}")
            print(f"📁 Working directory: {self.base_dir}")
            
            # Start the server process
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.base_dir),
                preexec_fn=os.setsid,
                text=True
            )
            
            print(f"✅ PDF Server process started (PID: {self.server_process.pid})")
            print(f"📁 Serving files from: {self.base_dir}")
            print(f"🌐 Base URL: {self.base_url}")
            
            # Give server a moment to start
            time.sleep(2)
            
            # Check if process is still alive
            if self.server_process.poll() is None:
                print(f"✅ Server process is running")
            else:
                print(f"❌ Server process died immediately")
                stdout, stderr = self.server_process.communicate()
                if stdout:
                    print(f"📤 Server stdout: {stdout}")
                if stderr:
                    print(f"📤 Server stderr: {stderr}")
                return False
            
            # Test server connectivity
            self.test_server()
            return True
            
        except Exception as e:
            print(f"❌ Failed to start PDF server: {e}")
            import traceback
            traceback.print_exc()
            return False

    
    def test_server(self):
        """Test if the server is responding"""
        try:
            print(f"🧪 Testing server connectivity...")
            import requests
            
            # Give server a moment to start
            time.sleep(1)
            
            response = requests.get(f"{self.base_url}/", timeout=5)
            print(f"✅ Server test successful: {response.status_code}")
            
        except Exception as e:
            print(f"❌ Server test failed: {e}")
    
    def stop_server(self):
        """Stop the HTTP server"""
        try:
            print(f"🛑 Stopping PDF server...")
            
            # Kill any process using our port (more aggressive approach)
            subprocess.run(
                ["pkill", "-f", f"http.server {self.port}"],
                capture_output=True
            )
            
            # Also try to kill by port number
            subprocess.run(
                ["lsof", "-ti", f":{self.port}"],
                capture_output=True
            )
            
            # If we have a server process, terminate it
            if self.server_process:
                try:
                    # Kill the entire process group
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                    self.server_process.wait(timeout=5)
                except:
                    # Force kill if graceful termination fails
                    try:
                        os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                    except:
                        pass
                self.server_process = None
                print(f"✅ Server process terminated")
                
        except Exception as e:
            print(f"⚠️ Warning stopping server: {e}")
    
    def upload_pdf(self, file_path: str, candidate_key: str, file_type: str = "resume") -> Optional[str]:
        """Upload a PDF file to the server and return the URL"""
        try:
            print(f"📤 Uploading PDF: {file_path} for {candidate_key}")
            
            # Clean candidate key for safe directory naming
            safe_candidate_key = candidate_key.replace(" ", "_").replace("(", "").replace(")", "")
            
            # Create candidate directory
            candidate_dir = self.base_dir / safe_candidate_key
            candidate_dir.mkdir(exist_ok=True)
            
            # Generate filename
            original_filename = Path(file_path).name
            safe_filename = original_filename.replace(" ", "_").replace("(", "").replace(")", "")
            new_filename = f"{file_type}_{safe_filename}"
            
            # Handle PDF conversion for non-PDF files
            if not original_filename.lower().endswith('.pdf'):
                pdf_filename = f"{file_type}_{Path(safe_filename).stem}.pdf"
                dest_path = candidate_dir / pdf_filename
                shutil.copy2(file_path, dest_path)
            else:
                dest_path = candidate_dir / new_filename
                shutil.copy2(file_path, dest_path)
            
            # Generate URL
            url = f"{self.base_url}/{safe_candidate_key}/{dest_path.name}"
            
            print(f"✅ PDF uploaded: {file_path} -> {url}")
            print(f"📁 File saved at: {dest_path}")
            
            # Verify file exists
            if dest_path.exists():
                file_size = dest_path.stat().st_size
                print(f"✅ File verified: {dest_path} ({file_size} bytes)")
            else:
                print(f"❌ File NOT found: {dest_path}")
            
            return url
            
        except Exception as e:
            print(f"❌ Failed to upload PDF: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def delete_pdf(self, pdf_url: str) -> bool:
        """Delete a PDF file from the server"""
        try:
            print(f"🗑️ Deleting PDF: {pdf_url}")
            
            # Extract path from URL and decode
            url_path = pdf_url.replace(self.base_url, "").lstrip("/")
            url_path = urllib.parse.unquote(url_path)
            file_path = self.base_dir / url_path
            
            if file_path.exists():
                file_path.unlink()
                print(f"✅ Deleted PDF: {pdf_url}")
                return True
            else:
                print(f"⚠️ PDF not found: {pdf_url}")
                return False
                
        except Exception as e:
            print(f"❌ Failed to delete PDF: {e}")
            return False
    
    def list_files(self):
        """Debug method to list all files"""
        print(f"📁 Files in {self.base_dir}:")
        try:
            for root, dirs, files in os.walk(self.base_dir):
                level = root.replace(str(self.base_dir), '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    file_path = Path(root) / file
                    file_size = file_path.stat().st_size
                    print(f"{subindent}{file} ({file_size} bytes)")
        except Exception as e:
            print(f"❌ Error listing files: {e}")
    
    def debug_status(self):
        """Print server status"""
        print(f"🔍 PDF Server Status:")
        print(f"   Base dir: {self.base_dir}")
        print(f"   Base URL: {self.base_url}")
        print(f"   Server process: {self.server_process is not None}")
        print(f"   Base dir exists: {self.base_dir.exists()}")
        
        if self.base_dir.exists():
            try:
                file_count = sum(1 for _ in self.base_dir.rglob('*') if _.is_file())
                print(f"   Total files: {file_count}")
            except Exception as e:
                print(f"   Error counting files: {e}")
        
        # Check if server is actually running
        if self.server_process:
            print(f"   Server PID: {self.server_process.pid}")
            print(f"   Server running: {self.server_process.poll() is None}")
    
    def restart_server(self):
        """Restart the server"""
        print(f"🔄 Restarting PDF server...")
        self.stop_server()
        time.sleep(2)  # Give it a moment
        self.start_server()
        
    # Add this method to the PDFServer class:

    def delete_all_files(self) -> bool:
        """Delete all files from the PDF server directory"""
        try:
            print(f"🗑️ Deleting all files from PDF server...")
            
            if self.base_dir.exists():
                # Get count before deletion
                file_count = sum(1 for _ in self.base_dir.rglob('*') if _.is_file())
                print(f"📊 Found {file_count} files to delete")
                
                # Remove all contents of the directory
                import shutil
                for item in self.base_dir.iterdir():
                    if item.is_file():
                        item.unlink()
                        print(f"🗑️ Deleted file: {item.name}")
                    elif item.is_dir():
                        shutil.rmtree(item)
                        print(f"🗑️ Deleted directory: {item.name}")
                
                print(f"✅ Successfully deleted all {file_count} files from PDF server")
                return True
            else:
                print(f"📁 PDF directory doesn't exist: {self.base_dir}")
                return False
                
        except Exception as e:
            print(f"❌ Error deleting all files: {e}")
            return False
    
    def __del__(self):
        """Clean up server on object destruction"""
        print(f"🧹 PDFServer destructor called")
        self.stop_server()

def delete_all_pdf_files():
    """Helper function to delete all PDF files from the server"""
    return pdf_server.delete_all_files()

# Update these functions to use the network IP:

def check_server_status():
    """Check if the server is actually running"""
    try:
        # Check if the process is still alive
        if pdf_server.server_process:
            poll_result = pdf_server.server_process.poll()
            if poll_result is None:
                print(f"✅ Server process is running (PID: {pdf_server.server_process.pid})")
            else:
                print(f"❌ Server process died with exit code: {poll_result}")
                return False
        else:
            print(f"❌ No server process found")
            return False
        
        # Check if port is actually being used
        result = subprocess.run(
            ["lsof", "-i", f":{pdf_server.port}"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ Port {pdf_server.port} is in use:")
            print(result.stdout)
        else:
            print(f"❌ Port {pdf_server.port} is not in use")
            return False
        
        # Test HTTP connection - USE NETWORK IP
        import requests
        response = requests.get(f"http://192.168.1.172:{pdf_server.port}/", timeout=2)
        print(f"✅ HTTP test successful: {response.status_code}")
        return True
        
    except Exception as e:
        print(f"❌ Server check failed: {e}")
        return False

def test_pdf_server():
    """Test function to check server connectivity"""
    print(f"🧪 Comprehensive server test...")
    
    # First check if server process is running
    if not check_server_status():
        print(f"🔄 Server not running properly, attempting restart...")
        pdf_server.restart_server()
        time.sleep(3)
        if not check_server_status():
            print(f"❌ Server restart failed")
            return False
    
    try:
        import requests
        
        # Test directory listing - USE NETWORK IP
        response = requests.get("http://192.168.1.172:8085/", timeout=5)
        print(f"✅ Directory listing test: {response.status_code}")
        print(f"📊 Response length: {len(response.text)} characters")
        
        # Show first 500 chars of response to debug
        print(f"📄 Response preview: {response.text[:500]}...")
        
        # Test with a specific file if available
        files = list(pdf_server.base_dir.rglob('*.pdf'))
        if files:
            test_file = files[0]
            relative_path = test_file.relative_to(pdf_server.base_dir)
            test_url = f"http://192.168.1.172:8085/{relative_path}"  # USE NETWORK IP
            print(f"🧪 Testing file access: {test_url}")
            
            file_response = requests.get(test_url, timeout=5)
            print(f"✅ File test: {file_response.status_code}")
            print(f"📊 File size: {len(file_response.content)} bytes")
        else:
            print(f"📁 No PDF files found to test")
        
        return True
        
    except Exception as e:
        print(f"❌ Server test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def debug_pdf_server():
    """Debug function to check server status"""
    print(f"🔍 Manual PDF server debug check:")
    pdf_server.debug_status()
    pdf_server.list_files()

def restart_pdf_server():
    """Restart the PDF server"""
    pdf_server.restart_server()

# Global PDF server instance
print(f"🌟 Creating global PDF server instance...")
pdf_server = PDFServer(port=8085)
print(f"🌟 Global PDF server created successfully")

# Wait a moment for server to fully start
time.sleep(2)

# Test the server immediately with comprehensive check
print(f"🔍 Running comprehensive server test...")
if not test_pdf_server():
    print(f"❌ Server test failed, trying manual restart...")
    pdf_server.restart_server()
    time.sleep(3)
    test_pdf_server()