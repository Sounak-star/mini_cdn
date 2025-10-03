# app_advanced.py - FIXED VERSION
import streamlit as st
import matplotlib.pyplot as plt
import pandas as pd
import time
import numpy as np
from client import (
    monitor_round, SERVERS, HOST, ping_once,
    compute_score, hybrid_prediction
)
from collections import deque

st.set_page_config(
    page_title="AI/ML Predictive Load Balancer", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
# Custom CSS - FIXED VERSION
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 10px;
        color: white;
        text-align: center;
    }
    
    /* Fix metric cards - dark background with visible text */
    .stMetric {
        background-color: #1e1e1e !important;
        padding: 15px !important;
        border-radius: 10px !important;
        border: 1px solid #333 !important;
    }
    
    /* Make metric labels visible */
    .stMetric label {
        color: #aaaaaa !important;
        font-size: 14px !important;
        font-weight: 500 !important;
    }
    
    /* Make metric values visible */
    .stMetric [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 24px !important;
        font-weight: bold !important;
    }
    
    /* Make metric deltas visible */
    .stMetric [data-testid="stMetricDelta"] {
        color: #4CAF50 !important;
    }
    
    /* Server titles */
    h3 {
        color: #ffffff !important;
    }
    
    /* Info boxes */
    .stInfo {
        background-color: #1e3a5f !important;
        color: #ffffff !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🚀 AI/ML Predictive Load Balancer Dashboard")
st.markdown("### Real-time Server Performance Monitoring & Prediction")

# Initialize session state for persistent data
if 'monitoring_data' not in st.session_state:
    st.session_state.monitoring_data = {
        'plot_time': [],
        'plot_data': {p: {
            'rtt': [], 
            'load': [], 
            'health': [],
            'errors': [],
            'chosen': []
        } for p in SERVERS},
        'rtt_history': {p: deque(maxlen=10) for p in SERVERS},
        'load_history': {p: deque(maxlen=10) for p in SERVERS},
        'health_history': {p: deque(maxlen=10) for p in SERVERS},
        'error_history': {p: deque(maxlen=10) for p in SERVERS},
        'selection_count': {p: 0 for p in SERVERS}
    }

if 'monitoring_active' not in st.session_state:
    st.session_state.monitoring_active = False

if 'current_round' not in st.session_state:
    st.session_state.current_round = 0

# Sidebar controls
st.sidebar.header("⚙️ Configuration")
rounds = st.sidebar.slider("Monitoring Rounds", 10, 200, 20)
interval = st.sidebar.slider("Round Interval (s)", 0.5, 5.0, 1.0, 0.5)

st.sidebar.markdown("---")
st.sidebar.subheader("Scoring Weights")
alpha = st.sidebar.number_input("RTT Weight (α)", min_value=0.0, max_value=10.0, value=1.0, step=0.1)
beta = st.sidebar.number_input("Load Weight (β)", min_value=0.0, max_value=10.0, value=0.5, step=0.1)
gamma = st.sidebar.number_input("Health Weight (γ)", min_value=0.0, max_value=10.0, value=0.3, step=0.1)
delta = st.sidebar.number_input("Error Weight (δ)", min_value=0.0, max_value=10.0, value=0.2, step=0.1)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Reset State"):
    st.session_state.monitoring_data = {
        'plot_time': [],
        'plot_data': {p: {
            'rtt': [], 
            'load': [], 
            'health': [],
            'errors': [],
            'chosen': []
        } for p in SERVERS},
        'rtt_history': {p: deque(maxlen=10) for p in SERVERS},
        'load_history': {p: deque(maxlen=10) for p in SERVERS},
        'health_history': {p: deque(maxlen=10) for p in SERVERS},
        'error_history': {p: deque(maxlen=10) for p in SERVERS},
        'selection_count': {p: 0 for p in SERVERS}
    }
    st.session_state.current_round = 0
    st.session_state.monitoring_active = False
    st.sidebar.success("State reset successfully!")
    st.rerun()

# Metrics display function
def create_metrics_row():
    data = st.session_state.monitoring_data
    cols = st.columns(len(SERVERS))
    
    for idx, port in enumerate(SERVERS):
        with cols[idx]:
            st.markdown(f"### 🖥️ Server {port}")
            if len(data['rtt_history'][port]) > 0:
                latest_rtt = data['rtt_history'][port][-1]
                latest_load = data['load_history'][port][-1]
                latest_health = data['health_history'][port][-1]
                latest_errors = data['error_history'][port][-1] * 100
                
                delta_rtt = None
                delta_load = None
                if len(data['rtt_history'][port]) > 1:
                    delta_rtt = f"{(latest_rtt - data['rtt_history'][port][-2])*1000:.1f}ms"
                if len(data['load_history'][port]) > 1:
                    delta_load = f"{(latest_load - data['load_history'][port][-2]):.0f}%"
                
                st.metric("RTT", f"{latest_rtt*1000:.1f}ms", delta=delta_rtt)
                st.metric("Load", f"{latest_load:.0f}%", delta=delta_load)
                st.metric("Health", f"{latest_health:.0f}/100")
                st.metric("Errors", f"{latest_errors:.2f}%")
            else:
                st.info("No data yet")

# Live plotting function
def plot_live_dashboard(best_server):
    data = st.session_state.monitoring_data
    
    if not data['plot_time']:
        st.warning("No data to plot yet...")
        return None
    
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.3)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 0])
    ax4 = fig.add_subplot(gs[1, 1])
    
    colors = ['#667eea', '#f093fb', '#4facfe']
    
    for idx, p in enumerate(SERVERS):
        color = colors[idx % len(colors)]
        alpha_val = 1.0 if p == best_server else 0.5
        linewidth = 2.5 if p == best_server else 1.5
        
        # RTT plot
        if data['plot_data'][p]['rtt']:
            ax1.plot(data['plot_time'], data['plot_data'][p]['rtt'], 
                    label=f"Server {p}", color=color, alpha=alpha_val, 
                    linewidth=linewidth, marker='o', markersize=4)
        
        # Load plot
        if data['plot_data'][p]['load']:
            ax2.plot(data['plot_time'], data['plot_data'][p]['load'], 
                    label=f"Server {p}", color=color, alpha=alpha_val, 
                    linewidth=linewidth, marker='o', markersize=4)
        
        # Health plot
        if data['plot_data'][p]['health']:
            ax3.plot(data['plot_time'], data['plot_data'][p]['health'], 
                    label=f"Server {p}", color=color, alpha=alpha_val, 
                    linewidth=linewidth, marker='o', markersize=4)
        
        # Errors plot
        if data['plot_data'][p]['errors']:
            ax4.plot(data['plot_time'], data['plot_data'][p]['errors'], 
                    label=f"Server {p}", color=color, alpha=alpha_val, 
                    linewidth=linewidth, marker='o', markersize=4)
        
        # Highlight current best
        if data['plot_time'] and p == best_server:
            if data['plot_data'][p]['rtt']:
                ax1.scatter(data['plot_time'][-1], data['plot_data'][p]['rtt'][-1], 
                           color='red', s=100, zorder=5, marker='*')
            if data['plot_data'][p]['load']:
                ax2.scatter(data['plot_time'][-1], data['plot_data'][p]['load'][-1], 
                           color='red', s=100, zorder=5, marker='*')
    
    ax1.set_title("📊 Round-Trip Time (RTT)", fontsize=12, fontweight='bold')
    ax1.set_ylabel("RTT (seconds)")
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    ax2.set_title("📈 Server Load", fontsize=12, fontweight='bold')
    ax2.set_ylabel("Load (%)")
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)
    
    ax3.set_title("💚 Health Score", fontsize=12, fontweight='bold')
    ax3.set_ylabel("Health (0-100)")
    ax3.set_xlabel("Time (seconds)")
    ax3.legend(loc='upper left')
    ax3.grid(True, alpha=0.3)
    
    ax4.set_title("⚠️ Error Rate", fontsize=12, fontweight='bold')
    ax4.set_ylabel("Errors (%)")
    ax4.set_xlabel("Time (seconds)")
    ax4.legend(loc='upper left')
    ax4.grid(True, alpha=0.3)
    
    return fig

# Custom monitoring function with persistent state
def monitor_round_with_state(round_idx, alpha, beta, gamma, delta):
    import json
    import socket
    
    data = st.session_state.monitoring_data
    results = {}
    
    # Ping all servers
    for p in SERVERS:
        try:
            s = socket.socket()
            s.settimeout(0.6)
            start = time.time()
            s.connect((HOST, p))
            s.send(b"ping")
            response = s.recv(2048).decode()
            end = time.time()
            s.close()
            
            metrics = json.loads(response)
            metrics['rtt'] = end - start
            results[p] = metrics
        except Exception as e:
            results[p] = None
    
    # Update histories
    for p, metrics in results.items():
        if metrics is None:
            continue
        
        data['rtt_history'][p].append(metrics['rtt'])
        data['load_history'][p].append(metrics['load'])
        data['health_history'][p].append(metrics.get('health_score', 50))
        
        error_rate = metrics.get('total_errors', 0) / max(1, metrics.get('total_handled', 1))
        data['error_history'][p].append(error_rate)
    
    # Compute predictions & scores
    predictions = {}
    for p in SERVERS:
        if len(data['rtt_history'][p]) == 0:
            predictions[p] = (None, None, None, 0, float('inf'))
            continue
        
        pred_rtt = np.mean(list(data['rtt_history'][p]))
        pred_load = np.mean(list(data['load_history'][p]))
        pred_health = np.mean(list(data['health_history'][p]))
        error_rate = np.mean(list(data['error_history'][p]))
        
        score = compute_score(pred_rtt, pred_load, pred_health, error_rate, alpha, beta, gamma, delta)
        predictions[p] = (pred_rtt, pred_load, pred_health, error_rate, score)
    
    # Select best server
    best_server = min(predictions.keys(), key=lambda x: predictions[x][4])
    data['selection_count'][best_server] += 1
    
    # Record plotting data
    timestamp = round_idx
    data['plot_time'].append(timestamp)
    
    for p in SERVERS:
        data['plot_data'][p]['rtt'].append(
            data['rtt_history'][p][-1] if len(data['rtt_history'][p]) > 0 else np.nan
        )
        data['plot_data'][p]['load'].append(
            data['load_history'][p][-1] if len(data['load_history'][p]) > 0 else np.nan
        )
        data['plot_data'][p]['health'].append(
            data['health_history'][p][-1] if len(data['health_history'][p]) > 0 else np.nan
        )
        data['plot_data'][p]['errors'].append(
            data['error_history'][p][-1] * 100 if len(data['error_history'][p]) > 0 else np.nan
        )
        data['plot_data'][p]['chosen'].append(1 if p == best_server else 0)
    
    return best_server

# Main content area
info_container = st.container()
metrics_container = st.container()
chart_container = st.container()

# Control buttons
col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    start_button = st.button("▶️ Start Monitoring", use_container_width=True, type="primary")
with col2:
    stop_button = st.button("⏸️ Stop", use_container_width=True)

if stop_button:
    st.session_state.monitoring_active = False

# Monitoring loop
if start_button:
    st.session_state.monitoring_active = True
    st.session_state.current_round = 0
    # Reset data
    st.session_state.monitoring_data = {
        'plot_time': [],
        'plot_data': {p: {
            'rtt': [], 
            'load': [], 
            'health': [],
            'errors': [],
            'chosen': []
        } for p in SERVERS},
        'rtt_history': {p: deque(maxlen=10) for p in SERVERS},
        'load_history': {p: deque(maxlen=10) for p in SERVERS},
        'health_history': {p: deque(maxlen=10) for p in SERVERS},
        'error_history': {p: deque(maxlen=10) for p in SERVERS},
        'selection_count': {p: 0 for p in SERVERS}
    }

if st.session_state.monitoring_active:
    with info_container:
        st.info(f"🔄 Monitoring in progress... Round {st.session_state.current_round + 1}/{rounds}")
    
    progress_bar = st.progress(0)
    
    for r in range(st.session_state.current_round, rounds):
        if not st.session_state.monitoring_active:
            st.warning("⏸️ Monitoring stopped by user")
            break
        
        # Run monitoring round
        best_server = monitor_round_with_state(r, alpha, beta, gamma, delta)
        st.session_state.current_round = r + 1
        
        # Update progress
        progress_bar.progress((r + 1) / rounds)
        
        # Update info
        with info_container:
            st.success(f"✅ Round {r+1} complete | Best Server: **{best_server}** ⭐")
        
        # Update metrics
        with metrics_container:
            create_metrics_row()
        
        # Update chart
        with chart_container:
            fig = plot_live_dashboard(best_server)
            if fig:
                st.pyplot(fig)
                plt.close()
        
        # Wait for next round
        if r < rounds - 1:
            time.sleep(interval)
    
    if st.session_state.current_round >= rounds:
        st.session_state.monitoring_active = False
        st.balloons()
        st.success(f"🎉 Monitoring complete! Processed {rounds} rounds.")
        
        # Final statistics
        st.markdown("---")
        st.subheader("📊 Final Statistics")
        
        data = st.session_state.monitoring_data
        stats_cols = st.columns(len(SERVERS))
        
        for idx, port in enumerate(SERVERS):
            with stats_cols[idx]:
                st.markdown(f"#### Server {port}")
                if len(data['rtt_history'][port]) > 0:
                    avg_rtt = np.mean(list(data['rtt_history'][port]))
                    avg_load = np.mean(list(data['load_history'][port]))
                    avg_health = np.mean(list(data['health_history'][port]))
                    times_selected = data['selection_count'][port]
                    
                    st.write(f"**Avg RTT:** {avg_rtt*1000:.1f}ms")
                    st.write(f"**Avg Load:** {avg_load:.1f}%")
                    st.write(f"**Avg Health:** {avg_health:.1f}/100")
                    st.write(f"**Times Selected:** {times_selected}")
                    
                    if rounds > 0:
                        percentage = (times_selected / rounds) * 100
                        st.write(f"**Selection Rate:** {percentage:.1f}%")
else:
    with info_container:
        st.info("👆 Click 'Start Monitoring' to begin")
    
    with metrics_container:
        st.markdown("### 📊 Server Metrics")
        st.write("Metrics will appear here once monitoring starts...")
    
    with chart_container:
        st.markdown("### 📈 Performance Charts")
        st.write("Charts will be displayed in real-time during monitoring...")

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666;'>
    <p>🤖 Powered by AI/ML Predictive Algorithms | Linear Regression + Exponential Smoothing</p>
</div>
""", unsafe_allow_html=True)