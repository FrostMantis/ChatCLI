import subprocess
import sys
import os
import signal

def run_application(flask_script="main.py", fastapi_script="app/websockets/main.py"):
    python = sys.executable
    processes = []

    try:
        if sys.platform == "win32":
            processes.append(subprocess.Popen([
                "cmd.exe", "/c", "start", "Flask Backend",
                "cmd.exe", "/k", f"{python} {flask_script}"
            ]))
            processes.append(subprocess.Popen([
                "cmd.exe", "/c", "start", "FastAPI Backend",
                "cmd.exe", "/k", f"{python} {fastapi_script}"
            ]))
            for p in processes:
                p.wait()
        else:
            processes.append(subprocess.Popen([python, flask_script]))
            processes.append(subprocess.Popen([python, fastapi_script]))

            def shutdown(sig, frame):
                print("\nShutting down servers...")
                for p in processes:
                    p.terminate()

            signal.signal(signal.SIGINT, shutdown)
            signal.signal(signal.SIGTERM, shutdown)

            for p in processes:
                p.wait()

    except Exception as e:
        input(f"An error occurred while starting the application: {e}\nPress Enter to exit...")
        raise

if __name__ == "__main__":
    run_application()
