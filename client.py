# client.py - Enhanced with iPerf bandwidth monitoring
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
ROUNDS = 20
ROUND_INTERVAL = 1.0
HISTORY_SIZE = 10
PREDICT_WINDOW = 5

# Weighted score parameters (updated for bandwidth)
ALPHA = 1.0      # weight for RTT
BETA = 0.5       # weight for load
GAMMA = 0.3      # weight for health score (inverse)
DELTA = 0.2      # weight for error rate
EPSILON = 0.4    # weight for bandwidth (NEW!)

SOCKET_TIMEOUT = 0.6
SHOW_ANALYSIS = True
# ----------------------------

# State
rtt_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
load_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
health_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
error_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
jitter_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}
bandwidth_history = {p: deque(maxlen=HISTORY_SIZE) for p in SERVERS}  # NEW!

# For plotting + summary
plot_time = []
plot_data = {p: {
    'rtt': [], 
    'load': [], 
    'health': [],
    'errors': [],
    'jitter': [],
    'bandwidth': [],  # NEW!
    'chosen': [],
    'scores': []
} for p in SERVERS}

state_lock = threading.Lock()

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
        print(f"⚠️  Failed to ping server on port {port}: {e}")
        return None

def exponential_smoothing(values, alpha=0.3):
    if len(values) == 0: return None
    if len(values) == 1: return float(values[0])
    smoothed = [values[0]]
    for i in range(1, len(values)):
        smoothed.append(alpha * values[i] + (1 - alpha) * smoothed[i-1])
    return float(smoothed[-1])

def predict_with_regression(values):
    if len(values) == 0: return None
    arr = np.array(values); n = len(arr)
    if n >= 2:
        m = min(n, PREDICT_WINDOW)
        y = arr[-m:]; X = np.arange(n-m, n).reshape(-1, 1)
        model = LinearRegression(); model.fit(X, y)
        return float(model.predict(np.array([[n]]))[0])
    else:
        return float(arr[-1])

def hybrid_prediction(values):
    smooth = exponential_smoothing(values)
    regress = predict_with_regression(values)
    if smooth is None or regress is None: return smooth or regress
    return 0.6 * regress + 0.4 * smooth

def compute_score(pred_rtt, pred_load, pred_health, error_rate, pred_bandwidth,
                  alpha=ALPHA, beta=BETA, gamma=GAMMA, delta=DELTA, epsilon=EPSILON):
    """
    Compute score with bandwidth consideration.
    Lower score is better, but higher bandwidth is better, so we invert it.
    """
    if pred_rtt is None: return float('inf')
    
    health_penalty = (100 - pred_health) / 100.0 if pred_health is not None else 1.0
    
    # Bandwidth bonus (higher bandwidth = lower score)
    # Normalize bandwidth (assume max 1000 Mbps)
    bandwidth_factor = 0
    if pred_bandwidth is not None and pred_bandwidth > 0:
        bandwidth_factor = (1000 - pred_bandwidth) / 1000.0  # Invert: lower = better
    
    score = (alpha * pred_rtt + 
             beta * (pred_load / 100.0) + 
             gamma * health_penalty + 
             delta * error_rate +
             epsilon * bandwidth_factor)
    
    return score

def detect_anomaly(values, threshold=2.0):
    if len(values) < 3: return False
    arr = np.array(values); mean = np.mean(arr[:-1]); std = np.std(arr[:-1])
    if std == 0: return False
    return abs((arr[-1] - mean) / std) > threshold

def monitor_round(round_idx):
    results = {}
    for p in SERVERS:
        metrics = ping_once(p)
        results[p] = metrics
    
    with state_lock:
        predictions = {}
        for p, metrics in results.items():
            if metrics is None:
                predictions[p] = (None, None, None, 0, None, float('inf'), False)
                continue
            
            # Update histories
            rtt_history[p].append(metrics['rtt'])
            load_history[p].append(metrics['load'])
            health_history[p].append(metrics.get('health_score', 50))
            error_rate = metrics.get('total_errors', 0) / max(1, metrics.get('total_handled', 1))
            error_history[p].append(error_rate)
            jitter_history[p].append(metrics.get('jitter', 0))
            bandwidth_history[p].append(metrics.get('bandwidth_mbps', 500))  # NEW!
            
            # Predictions
            pred_rtt = hybrid_prediction(list(rtt_history[p]))
            pred_load = hybrid_prediction(list(load_history[p]))
            pred_health = np.mean(list(health_history[p])) if len(health_history[p]) > 0 else 50
            error_rate = np.mean(list(error_history[p])) if len(error_history[p]) > 0 else 0
            pred_bandwidth = hybrid_prediction(list(bandwidth_history[p]))  # NEW!
            
            is_anomaly = detect_anomaly(list(rtt_history[p]))
            score = compute_score(pred_rtt, pred_load, pred_health, error_rate, pred_bandwidth)
            if is_anomaly: score *= 1.5
            
            predictions[p] = (pred_rtt, pred_load, pred_health, error_rate, pred_bandwidth, score, is_anomaly)
        
        # Pick best server this round
        best_server = min(predictions.keys(), key=lambda x: predictions[x][5])
        
        # Store for plotting & summary
        timestamp = round_idx * ROUND_INTERVAL
        plot_time.append(timestamp)
        for p in SERVERS:
            pred_rtt, pred_load, pred_health, error_rate, pred_bandwidth, score, _ = predictions[p]
            plot_data[p]['rtt'].append(rtt_history[p][-1] if len(rtt_history[p]) > 0 else np.nan)
            plot_data[p]['load'].append(load_history[p][-1] if len(load_history[p]) > 0 else np.nan)
            plot_data[p]['health'].append(health_history[p][-1] if len(health_history[p]) > 0 else np.nan)
            plot_data[p]['errors'].append(error_history[p][-1] * 100 if len(error_history[p]) > 0 else np.nan)
            plot_data[p]['jitter'].append(jitter_history[p][-1] * 1000 if len(jitter_history[p]) > 0 else np.nan)
            plot_data[p]['bandwidth'].append(bandwidth_history[p][-1] if len(bandwidth_history[p]) > 0 else np.nan)  # NEW!
            plot_data[p]['chosen'].append(1 if p == best_server else 0)
            plot_data[p]['scores'].append(score)
        
        # Print round summary with bandwidth
        print(f"\n📊 Round {round_idx + 1}/{ROUNDS}")
        print(f"{'Port':<8} {'RTT (ms)':<12} {'Load %':<10} {'Health':<10} {'Bandwidth':<15} {'Score':<10}")
        print("-" * 75)
        for p in SERVERS:
            pred_rtt, pred_load, pred_health, _, pred_bw, score, _ = predictions[p]
            marker = "⭐" if p == best_server else "  "
            rtt_str = f"{pred_rtt*1000:.1f}" if pred_rtt else "N/A"
            load_str = f"{pred_load:.1f}" if pred_load else "N/A"
            health_str = f"{pred_health:.1f}" if pred_health else "N/A"
            bw_str = f"{pred_bw:.1f} Mbps" if pred_bw else "N/A"
            score_str = f"{score:.3f}" if score != float('inf') else "INF"
            print(f"{marker} {p:<6} {rtt_str:<12} {load_str:<10} {health_str:<10} {bw_str:<15} {score_str:<10}")

def final_summary():
    """Calculate overall best server at the end"""
    avg_scores = {}
    for p in SERVERS:
        scores = [s for s in plot_data[p]['scores'] if np.isfinite(s)]
        avg_scores[p] = np.mean(scores) if scores else float('inf')
    
    best_server = min(avg_scores, key=avg_scores.get)
    
    print("\n" + "="*60)
    print(" FINAL SUMMARY (WITH BANDWIDTH)")
    print("="*60)
    for p in SERVERS:
        avg_bw = np.mean([b for b in plot_data[p]['bandwidth'] if not np.isnan(b)])
        print(f"Server {p}: Avg Score = {avg_scores[p]:.3f} | Avg Bandwidth = {avg_bw:.1f} Mbps")
    print(f"\n✅ Best Server Overall: {best_server} (Lowest Avg Score {avg_scores[best_server]:.3f})")
    
    return best_server

def show_analysis():
    """Show plots for analysis including bandwidth"""
    fig, ((ax1, ax2), (ax3, ax4), (ax5, ax6)) = plt.subplots(3, 2, figsize=(16, 12))
    
    for p in SERVERS:
        ax1.plot(plot_time, plot_data[p]['rtt'], label=f"Server {p}", marker='o', markersize=3)
        ax2.plot(plot_time, plot_data[p]['load'], label=f"Server {p}", marker='o', markersize=3)
        ax3.plot(plot_time, plot_data[p]['health'], label=f"Server {p}", marker='o', markersize=3)
        ax4.plot(plot_time, plot_data[p]['errors'], label=f"Server {p}", marker='o', markersize=3)
        ax5.plot(plot_time, plot_data[p]['bandwidth'], label=f"Server {p}", marker='o', markersize=3)  # NEW!
        ax6.plot(plot_time, plot_data[p]['scores'], label=f"Server {p}", marker='o', markersize=3)
    
    ax1.set_title("RTT (seconds)"); ax1.set_ylabel("RTT (s)"); ax1.legend(); ax1.grid(True, alpha=0.3)
    ax2.set_title("Server Load (%)"); ax2.set_ylabel("Load (%)"); ax2.legend(); ax2.grid(True, alpha=0.3)
    ax3.set_title("Health Score"); ax3.set_ylabel("Health (0-100)"); ax3.legend(); ax3.grid(True, alpha=0.3)
    ax4.set_title("Error Rate (%)"); ax4.set_ylabel("Errors (%)"); ax4.legend(); ax4.grid(True, alpha=0.3)
    ax5.set_title("Bandwidth (Mbps)"); ax5.set_ylabel("Bandwidth"); ax5.set_xlabel("Time (s)"); ax5.legend(); ax5.grid(True, alpha=0.3)  # NEW!
    ax6.set_title("Server Scores"); ax6.set_ylabel("Score (lower=better)"); ax6.set_xlabel("Time (s)"); ax6.legend(); ax6.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()

def main():
    print("Starting Enhanced Predictive Load Balancer with iPerf Bandwidth Monitoring...")
    print(f"Monitoring {len(SERVERS)} servers: {SERVERS}")
    print(f"Bandwidth weight (ε): {EPSILON}")
    
    for round_idx in range(ROUNDS):
        monitor_round(round_idx)
        time.sleep(ROUND_INTERVAL)
    
    # Show summary after all rounds
    best = final_summary()
    
    if SHOW_ANALYSIS:
        print("\n📊 Showing Analysis Charts...")
        show_analysis()

if __name__ == "__main__":
    main()
