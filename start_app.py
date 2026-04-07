import subprocess
import webbrowser
import time

PI_IP = "192.168.43.100"  # Pi's static IP on hotspot
USERNAME = "pi"
APP_PATH = "/home/pi/your_app_folder"  # Adjust to your Pi folder

def start_on_pi():
    # Kill old process
    subprocess.run(["ssh", f"{USERNAME}@{PI_IP}", "pkill -f 'app.py'"], capture_output=True)
    time.sleep(2)
    
    # Start new (detached)
    cmd = f"cd {APP_PATH} && nohup python3 app.py > app.log 2>&1 &"
    subprocess.run(["ssh", f"{USERNAME}@{PI_IP}", cmd], capture_output=True)
    print(f"Started app on Pi ({PI_IP})!")

if __name__ == "__main__":
    start_on_pi()
    time.sleep(5)  # Wait for startup
    webbrowser.open("http://posture.local:5000")  # Open on laptop
    print("Open http://posture.local:5000 on phone (bookmark it). Check Pi logs: ssh pi@PI_IP 'tail -f app.log'")