# edge_server.py - ENHANCED VERSION
import socket
import threading
import random
import time
import sys
import json

if len(sys.argv) != 2:
    print("Usage: python edge_server.py <PORT>")
    sys.exit(1)

PORT = int(sys.argv[1])
HOST = '127.0.0.1'

# Persistent server state (shared across threads)
state_lock = threading.Lock()
current_load = random.randint(20, 40)
connections_handled = 0
active_connections = 0
total_errors = 0
request_queue = 0

# Enhanced parameters
LOAD_INCREASE_MIN = 2
LOAD_INCREASE_MAX = 6
LOAD_DECREASE_MIN = 2
LOAD_DECREASE_MAX = 4
BASE_LATENCY_MIN = 0.03
BASE_LATENCY_MAX = 0.06
LOAD_TO_LATENCY_FACTOR = 0.003

# New: Jitter and packet loss simulation
JITTER_MAX = 0.015  # max jitter in seconds
PACKET_LOSS_BASE = 0.01  # 1% base packet loss
PACKET_LOSS_LOAD_FACTOR = 0.0005  # increases with load

# Server capacity simulation
MAX_QUEUE_SIZE = 20
OVERLOAD_THRESHOLD = 85

def simulate_packet_loss():
    """Simulate packet loss based on current load"""
    loss_probability = PACKET_LOSS_BASE + (current_load * PACKET_LOSS_LOAD_FACTOR)
    return random.random() < loss_probability

def calculate_metrics():
    """Calculate comprehensive server metrics"""
    with state_lock:
        # Health score (0-100, higher is better)
        health = 100 - current_load
        if current_load > OVERLOAD_THRESHOLD:
            health = max(0, health - 20)
        if request_queue > MAX_QUEUE_SIZE * 0.7:
            health -= 15
        
        # Jitter calculation
        jitter = random.uniform(0, JITTER_MAX) * (current_load / 100.0)
        
        return {
            'load': current_load,
            'active_connections': active_connections,
            'total_handled': connections_handled,
            'total_errors': total_errors,
            'queue_depth': request_queue,
            'health_score': max(0, min(100, health)),
            'jitter': jitter
        }

def handle_client(conn, addr):
    global current_load, connections_handled, active_connections, total_errors, request_queue
    
    # Add to queue
    with state_lock:
        request_queue += 1
        active_connections += 1
        connections_handled += 1
        current_load += random.randint(LOAD_INCREASE_MIN, LOAD_INCREASE_MAX)
        if current_load > 100:
            current_load = 100
    
    try:
        data = conn.recv(1024)
        if not data:
            return
        
        # Simulate packet loss
        if simulate_packet_loss():
            with state_lock:
                total_errors += 1
            conn.close()
            return
        
        # Calculate latency with jitter
        base_latency = random.uniform(BASE_LATENCY_MIN, BASE_LATENCY_MAX)
        load_latency = current_load * LOAD_TO_LATENCY_FACTOR
        jitter = random.uniform(-JITTER_MAX, JITTER_MAX) * (current_load / 100.0)
        latency = max(0.01, base_latency + load_latency + jitter)
        
        # Simulate processing
        time.sleep(latency)
        
        # Get comprehensive metrics
        metrics = calculate_metrics()
        metrics['latency'] = latency
        
        # Send JSON response
        response = json.dumps(metrics)
        conn.send(response.encode())
        
    except Exception as e:
        with state_lock:
            total_errors += 1
    finally:
        conn.close()
        with state_lock:
            request_queue = max(0, request_queue - 1)
            decrease = random.randint(LOAD_DECREASE_MIN, LOAD_DECREASE_MAX)
            current_load = max(2, current_load - decrease)
            active_connections -= 1

def background_load_fluctuation():
    """Simulate realistic background load changes"""
    global current_load
    while True:
        time.sleep(random.uniform(2, 5))
        with state_lock:
            # Random load fluctuation
            change = random.randint(-5, 5)
            current_load = max(5, min(95, current_load + change))

def start_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        s.bind((HOST, PORT))
    except OSError as e:
        print(f"Error binding to {HOST}:{PORT} -> {e}")
        sys.exit(1)
    
    s.listen(50)
    print(f"[SERVER {PORT}] Running on {HOST}:{PORT} (initial load {current_load}%)")
    
    # Start background load fluctuation thread
    bg_thread = threading.Thread(target=background_load_fluctuation, daemon=True)
    bg_thread.start()
    
    try:
        while True:
            conn, addr = s.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[SERVER] Shutting down")
    finally:
        s.close()

if __name__ == "__main__":
    start_server()