import paramiko
import socket
from typing import Optional


class SFTPConnection:
    def __init__(self, host: str, port: int, username: str, password: str, timeout: int = 30):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self) -> bool:
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.timeout,
                allow_agent=False,
                look_for_keys=False,
            )
            self.sftp = self.client.open_sftp()
            print(f"Successfully connected to {self.host}:{self.port}")
            return True
        except paramiko.AuthenticationException:
            print("Error: Authentication failed. Please check your username and password.")
            return False
        except paramiko.SSHException as e:
            print(f"Error: SSH connection failed - {str(e)}")
            return False
        except socket.timeout:
            print(f"Error: Connection to {self.host}:{self.port} timed out.")
            return False
        except Exception as e:
            print(f"Error: Failed to connect - {str(e)}")
            return False

    def disconnect(self):
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.client:
            self.client.close()
            self.client = None
        print("Connection closed.")

    def is_connected(self) -> bool:
        return self.sftp is not None and self.client is not None
