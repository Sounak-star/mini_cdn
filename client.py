# client.py - ENHANCED VERSION
import socket
import time
import threading
import numpy as np
import json
from collections import deque
from sklearn.linear_model import LinearRegression
import matplotlib.pyplot as plt

# ---------- CONFIG ----------
SERVERS = [8001, 8002, 8003]
HOST = '127.0.0.1'
ROUNDS = 60
ROUND_INTERVAL = 1.0
HISTORY_SIZE = 10
PREDICT_WINDOW = 5

# Weighted score parameters (can be modified)
ALPHA = 1.0      # weight for RTT
BETA = 0.5       # weight for load
GAMMA = 0.3      # weight for health score (inverse)
DELTA = 0.2      # weight for error rate

SOCKET_TIMEOUT = 0.6
ENABLE_PLOT = True
# ----------------------------

# State
rtt_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
load_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
health_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
error_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
jitter_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}

# For plotting
plot_time = []
plot_data = {p: {
    'rtt': [], 
    'load': [], 
    'health': [],
    'errors': [],
    'jitter': [],
    'chosen': []
} for p in SERVERS}

state_lock = threading.Lock()

def reset_state():
    """Reset all state - useful for Streamlit reruns"""
    global rtt_history, load_history, health_history, error_history, jitter_history, plot_time, plot_data
    rtt_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
    load_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
    health_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
    error_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
    jitter_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
    plot_time = []
    plot_data = {p: {
        'rtt': [], 
        'load': [], 
        'health': [],
        'errors': [],
        'jitter': [],
        'chosen': []
    } for p in SERVERS}

def ping_once(port):
    """Sends a ping; returns metrics dict or None on failure."""
    try:
        s = socket.socket()
        s.settimeout(SOCKET_TIMEOUT)
        start = time.time()
        s.connect((HOST, port))
        s.send(b"ping")
        data = s.recv(2048).decode()
        end = time.time()
        s.close()
        
        metrics = json.loads(data)
        metrics['rtt'] = end - start
        return metrics
    except Exception as e:
        return None

def exponential_smoothing(values, alpha=0.3):
    """Apply exponential smoothing to values"""
    if len(values) == 0:
        return None
    if len(values) == 1:
        return float(values[0])
    
    smoothed = [values[0]]
    for i in range(1, len(values)):
        smoothed.append(alpha * values[i] + (1 - alpha) * smoothed[i-1])
    return float(smoothed[-1])

def predict_with_regression(values):
    """Linear regression prediction"""
    if len(values) == 0:
        return None
    arr = np.array(values)
    n = len(arr)
    if n >= 2:
        m = min(n, PREDICT_WINDOW)
        y = arr[-m:]
        X = np.arange(n-m, n).reshape(-1, 1)
        model = LinearRegression()
        model.fit(X, y)
        next_x = np.array([[n]])
        pred = model.predict(next_x)[0]
        return float(pred)
    else:
        return float(arr[-1])

def hybrid_prediction(values):
    """Combine exponential smoothing and regression"""
    smooth = exponential_smoothing(values)
    regress = predict_with_regression(values)
    
    if smooth is None or regress is None:
        return smooth or regress
    
    # Weight recent data more heavily
    return 0.6 * regress + 0.4 * smooth

def compute_score(pred_rtt, pred_load, pred_health, error_rate, alpha=ALPHA, beta=BETA, gamma=GAMMA, delta=DELTA):
    """Calculate weighted score (lower is better)"""
    if pred_rtt is None:
        return float('inf')
    
    # Normalize health (invert since higher health is better)
    health_penalty = (100 - pred_health) / 100.0 if pred_health is not None else 1.0
    
    score = (
        alpha * pred_rtt + 
        beta * (pred_load / 100.0) + 
        gamma * health_penalty +
        delta * error_rate
    )
    return score

def detect_anomaly(values, threshold=2.0):
    """Detect if latest value is anomalous (z-score based)"""
    if len(values) < 3:
        return False
    arr = np.array(values)
    mean = np.mean(arr[:-1])
    std = np.std(arr[:-1])
    if std == 0:
        return False
    z_score = abs((arr[-1] - mean) / std)
    return z_score > threshold

def monitor_round(round_idx, alpha=ALPHA, beta=BETA, gamma=GAMMA, delta=DELTA):
    """One monitoring round with enhanced metrics"""
    results = {}
    
    for p in SERVERS:
        metrics = ping_once(p)
        results[p] = metrics
    
    with state_lock:
        for p, metrics in results.items():
            if metrics is None:
                continue
            
            rtt_history[p].append(metrics['rtt'])
            load_history[p].append(metrics['load'])
            health_history[p].append(metrics.get('health_score', 50))
            
            # Track errors
            error_rate = metrics.get('total_errors', 0) / max(1, metrics.get('total_handled', 1))
            error_history[p].append(error_rate)
            
            # Track jitter
            jitter_history[p].append(metrics.get('jitter', 0))
        
        # Compute predictions & scores
        predictions = {}
        for p in SERVERS:
            if len(rtt_history[p]) == 0:
                predictions[p] = (None, None, None, 0, float('inf'), False)
                continue
            
            pred_rtt = hybrid_prediction(list(rtt_history[p]))
            pred_load = hybrid_prediction(list(load_history[p]))
            pred_health = np.mean(list(health_history[p])) if len(health_history[p]) > 0 else 50
            error_rate = np.mean(list(error_history[p])) if len(error_history[p]) > 0 else 0
            
            # Anomaly detection
            is_anomaly = detect_anomaly(list(rtt_history[p]))
            
            score = compute_score(pred_rtt, pred_load, pred_health, error_rate, alpha, beta, gamma, delta)
            
            # Penalize if anomaly detected
            if is_anomaly:
                score *= 1.5
            
            predictions[p] = (pred_rtt, pred_load, pred_health, error_rate, score, is_anomaly)
        
        # Select best server
        best_server = min(predictions.keys(), key=lambda x: predictions[x][4])
        
        # Record plotting data
        timestamp = round_idx * ROUND_INTERVAL
        plot_time.append(timestamp)
        
        for p in SERVERS:
            plot_data[p]['rtt'].append(rtt_history[p][-1] if len(rtt_history[p]) > 0 else np.nan)
            plot_data[p]['load'].append(load_history[p][-1] if len(load_history[p]) > 0 else np.nan)
            plot_data[p]['health'].append(health_history[p][-1] if len(health_history[p]) > 0 else np.nan)
            plot_data[p]['errors'].append(error_history[p][-1] * 100 if len(error_history[p]) > 0 else np.nan)
            plot_data[p]['jitter'].append(jitter_history[p][-1] * 1000 if len(jitter_history[p]) > 0 else np.nan)
            plot_data[p]['chosen'].append(1 if p == best_server else 0)
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"Round {round_idx+1}")
        print(f"{'='*60}")
        for p in SERVERS:
            pred_rtt, pred_load, pred_health, error_rate, score, is_anomaly = predictions[p]
            anomaly_flag = " ⚠️ ANOMALY" if is_anomaly else ""
            best_flag = " ⭐ SELECTED" if p == best_server else ""
            print(f"Server {p}:{best_flag}{anomaly_flag}")
            print(f"  RTT: {pred_rtt:.3f}s | Load: {pred_load:.1f}% | Health: {pred_health:.1f}")
            print(f"  Errors: {error_rate*100:.2f}% | Score: {score:.3f}")
    
    return best_server

def main():
    """Main monitoring loop"""
    print("Starting Enhanced Predictive Load Balancer...")
    print(f"Monitoring {len(SERVERS)} servers: {SERVERS}")
    
    for round_idx in range(ROUNDS):
        monitor_round(round_idx)
        time.sleep(ROUND_INTERVAL)
    
    if ENABLE_PLOT:
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(14, 10))
        
        for p in SERVERS:
            ax1.plot(plot_time, plot_data[p]['rtt'], label=f"Server {p}", marker='o', markersize=3)
            ax2.plot(plot_time, plot_data[p]['load'], label=f"Server {p}", marker='o', markersize=3)
            ax3.plot(plot_time, plot_data[p]['health'], label=f"Server {p}", marker='o', markersize=3)
            ax4.plot(plot_time, plot_data[p]['errors'], label=f"Server {p}", marker='o', markersize=3)
        
        ax1.set_title("RTT (seconds)")
        ax1.set_ylabel("RTT (s)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        ax2.set_title("Server Load (%)")
        ax2.set_ylabel("Load (%)")
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        ax3.set_title("Health Score")
        ax3.set_ylabel("Health (0-100)")
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        ax4.set_title("Error Rate (%)")
        ax4.set_ylabel("Errors (%)")
        ax4.set_xlabel("Time (s)")
        ax4.legend()
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()

if __name__ == "__main__":
    main()