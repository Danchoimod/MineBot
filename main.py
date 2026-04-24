import sys
from raknet import RakNetProtocol

def main():
    host = "127.0.0.1" # Changed default to localhost since user is running MCPE on Windows 10
    port = 19132
    
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])

    print("Starting Minebot Python Clone...")
    client = RakNetProtocol(host, port)
    
    try:
        client.run()
    except KeyboardInterrupt:
        print("\nStopping...")

if __name__ == "__main__":
    main()
