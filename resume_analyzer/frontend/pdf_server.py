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
        self.base_dir = Path(base_dir)
        self.port = port
        self.base_url = f"http://192.168.1.172:{port}"
        self.server_process = None
        
        # Create base directory if it doesn't exist
        self.base_dir.mkdir(exist_ok=True)
        
        # Start the server
        self.start_server()
    
    def start_server(self):
        """Start the HTTP server using Python's built-in server"""
        try:
            # Kill any existing server on this port
            self.stop_server()
            time.sleep(1)
            
            # Use Python's built-in HTTP server - bind to all interfaces
            cmd = [
                "python3", "-m", "http.server", str(self.port),
                "--directory", str(self.base_dir),
                "--bind", "0.0.0.0"
            ]
            
            # Start the server process
            self.server_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.base_dir),
                preexec_fn=os.setsid,
                text=True
            )
            
            # Give server a moment to start
            time.sleep(2)
            
            # Check if process is still alive
            if self.server_process.poll() is None:
                return True
            else:
                return False
            
        except Exception as e:
            print(f"❌ Failed to start PDF server: {e}")
            return False

    def test_server(self):
        """Test if the server is responding"""
        try:
            import requests
            time.sleep(1)
            response = requests.get(f"{self.base_url}/", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def stop_server(self):
        """Stop the HTTP server"""
        try:
            # Kill any process using our port
            subprocess.run(
                ["pkill", "-f", f"http.server {self.port}"],
                capture_output=True
            )
            
            # If we have a server process, terminate it
            if self.server_process:
                try:
                    os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
                    self.server_process.wait(timeout=5)
                except:
                    try:
                        os.killpg(os.getpgid(self.server_process.pid), signal.SIGKILL)
                    except:
                        pass
                self.server_process = None
                
        except Exception:
            pass
    
    def upload_pdf(self, file_path: str, candidate_key: str, file_type: str = "resume") -> Optional[str]:
        """Upload a PDF file to the server and return the URL"""
        try:
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
            return url
            
        except Exception as e:
            print(f"❌ Failed to upload PDF: {e}")
            return None
    
    def delete_pdf(self, pdf_url: str) -> bool:
        """Delete a PDF file from the server"""
        try:
            # Extract path from URL and decode
            url_path = pdf_url.replace(self.base_url, "").lstrip("/")
            url_path = urllib.parse.unquote(url_path)
            file_path = self.base_dir / url_path
            
            if file_path.exists():
                file_path.unlink()
                return True
            else:
                return False
                
        except Exception:
            return False
    
    def list_files(self):
        """Debug method to list all files"""
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
        self.stop_server()
        time.sleep(2)
        self.start_server()
        
    def delete_all_files(self) -> bool:
        """Delete all files from the PDF server directory"""
        try:
            if self.base_dir.exists():
                file_count = sum(1 for _ in self.base_dir.rglob('*') if _.is_file())
                
                import shutil
                for item in self.base_dir.iterdir():
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                
                print(f"✅ Deleted {file_count} files from PDF server")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"❌ Error deleting all files: {e}")
            return False
    
    def __del__(self):
        """Clean up server on object destruction"""
        self.stop_server()

def delete_all_pdf_files():
    """Helper function to delete all PDF files from the server"""
    return pdf_server.delete_all_files()

def check_server_status():
    """Check if the server is actually running"""
    try:
        if not pdf_server.server_process or pdf_server.server_process.poll() is not None:
            return False
        
        # Test HTTP connection
        import requests
        response = requests.get(f"http://192.168.1.172:{pdf_server.port}/", timeout=2)
        return response.status_code == 200
        
    except Exception:
        return False

def test_pdf_server():
    """Test function to check server connectivity"""
    if not check_server_status():
        pdf_server.restart_server()
        time.sleep(3)
        return check_server_status()
    return True

def debug_pdf_server():
    """Debug function to check server status"""
    pdf_server.debug_status()
    pdf_server.list_files()

def restart_pdf_server():
    """Restart the PDF server"""
    pdf_server.restart_server()

# Global PDF server instance
pdf_server = PDFServer(port=8085)

# Wait and test
time.sleep(2)
if not test_pdf_server():
    pdf_server.restart_server()
    time.sleep(3)