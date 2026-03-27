#!/usr/bin/env python3
"""
ESP32-S3 BLE センサーデータ可視化
300Hz リアルタイム表示対応
"""
import asyncio
import sys
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, QObject
import pyqtgraph as pg
import qasync
from qasync import asyncSlot, QEventLoop

from collections import deque
import gzip
import csv
from datetime import datetime
import struct
from pathlib import Path


import dataset_utils


try:
    from bleak import BleakClient, BleakScanner
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

try:
    from pylsl import StreamInlet, resolve_byprop
    PYLSL_AVAILABLE = True
except ImportError:
    PYLSL_AVAILABLE = False

# ESP32のBLE UUIDs
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
CHARACTERISTIC_UUID_TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# LSL設定
DATASET_ROOT = "./DOG_BEHAVIOUR_DATASET/project-01"

class LSLTriggerWorker(QThread):
    """LSL trigger receive worker"""
    trigger_received = pyqtSignal(str, str, str, str, str, str, str)
    connection_status = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.inlet = None

    def run(self):
        """LSLトリガー受信メインループ"""
        try:
            # RecordingTriggerストリームを検索
            self.connection_status.emit(False, "Searching for LSL trigger stream...")
            print("Resolving LSL stream 'RecordingTrigger'...")
            streams = resolve_byprop('name', 'RecordingTrigger', timeout=5.0)

            if not streams:
                self.connection_status.emit(False, "LSL trigger stream not found")
                return

            # Inlet作成
            self.inlet = StreamInlet(streams[0])
            self.running = True
            self.connection_status.emit(True, "LSL trigger stream connected")
            print("✅ LSL trigger stream connected")

            # トリガー受信ループ
            while self.running:
                sample, timestamp = self.inlet.pull_sample(timeout=0.01)
                if sample:
                    trigger = sample[0]
                    # used for output files
                    session_dir = sample[1] if len(sample) > 1 else ""
                    output_filename_prefix = sample[2] if len(sample) > 2 else ""
                    run_id = sample[3] if len(sample) > 3 else ""
                    # used for metadata files
                    participant_id = sample[4] if len(sample) > 4 else ""
                    session_id = sample[5] if len(sample) > 5 else ""
                    task_long_name = sample[6] if len(sample) > 6 else ""
                    
                    print(f"📥 Received LSL trigger: {trigger}, {session_dir}, {output_filename_prefix}, {run_id}, {participant_id}, {session_id}, {task_long_name}")
                    self.trigger_received.emit(trigger, session_dir, output_filename_prefix, run_id, participant_id, session_id, task_long_name)
        except Exception as e:
            self.connection_status.emit(False, f"LSL connection failed: {str(e)}")
            print(f"❌ LSL error: {e}")
        finally:
            self.running = False

    def stop(self):
        """ワーカー停止"""
        self.running = False
        self.wait()

class BLEWorker(QObject): 
    """
    Changed from QThread to QObject.
    Windows BLE must run on the main thread's Async loop.
    """
    data_received = pyqtSignal(bytes)
    connection_status = pyqtSignal(bool, str)
    
    def __init__(self):
        super().__init__()
        self.client = None
        self.running = False
        self.device_address = None
        
    def set_device_address(self, address):
        self.device_address = address
        
    def notification_handler(self, sender, data):
        """BLE通知データ受信ハンドラ（バイナリ形式）"""
        try:
            # バイナリデータをbytes型に変換して送信
            if data:
                self.data_received.emit(bytes(data))
        except Exception as e:
            print(f"Data decode error: {e}")
    
    async def start(self):
        """Replaces run(). Called asynchronously."""
        try:
            self.client = BleakClient(self.device_address)
            await self.client.connect()
            self.running = True
            self.connection_status.emit(True, f"Connected to {self.device_address}")
            
            # 通知開始
            await self.client.start_notify(CHARACTERISTIC_UUID_TX, self.notification_handler)
            
            # Keep connection alive
            while self.running and self.client.is_connected:
                await asyncio.sleep(0.1)
                
        except Exception as e:
            self.connection_status.emit(False, f"Connection failed: {str(e)}")
        finally:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
            self.running = False
    
    async def disconnect(self):
        """Stop method"""
        self.running = False
        if self.client:
            await self.client.disconnect()

class ESP32BLESensorVisualizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ESP32-S3 BLE Sensor Visualizer (ECG:300Hz/MPU:100Hz)')
        self.setGeometry(100, 100, 1400, 1000)

        self.toggle_is_start = True # if true the button for manually start/stop the recording has "Start Recording" text

        # メインウィジェット
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)

        # 時間窓設定
        self.time_window = 5.0

        # BLE Worker Setup
        self.ble_worker = BLEWorker()
        self.ble_worker.data_received.connect(self.process_data)
        self.ble_worker.connection_status.connect(self.on_connection_status)
        self.ble_task = None # Handle for the async task

        # LSL trigger worker
        self.lsl_worker = None
        self.lsl_connected = False
        
        # Init Variables
        self.current_session_dir = ""
        self.current_output_filename_prefix = ""
        self.current_run_id = ""
        self.current_participant_id = ""
        self.current_session_id = ""
        self.current_task_long_name = ""
        
        # コントロールパネル
        self.setup_control_panel()

        # グラフ設定
        self.setup_graphs()

        # データバッファ
        self.buffer_size = int(300 * self.time_window)
        self.init_data_buffers()

        # start time
        self.start_time = None

        # the way acq_time works is that it is set when recording starts, and saved when recording stops
        # when the recording stops the variable gets setted to None again, so that next time the recording starts it will get setted again
        # this variable is only edited when is None, this way is possible to capture the moment the first data comes
        self.acq_time = None
        self.acq_time_correct = None

        # Keep last MPU data (for interpolation)
        self.last_mpu_data = None

        # Display update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(3)  # 300Hz表示更新

        # TSV記録
        self.tsv_file_ecg = None
        self.tsv_writer_ecg = None
        self.tsv_file_mpu = None
        self.tsv_writer_mpu = None
        self.recording = False
        self.data_counter = 0 # goes from 0 to 2, every time it is 0, write the mpu data (since mpu freqency is 3 times slower than ecg)

        # デバイスリスト更新
        self.scan_devices()

    def init_data_buffers(self):
        """データバッファ初期化"""
        self.timestamps = deque(maxlen=self.buffer_size)
        self.ecg1_data = deque(maxlen=self.buffer_size)
        self.ecg2_data = deque(maxlen=self.buffer_size)
        self.mpu1_ax = deque(maxlen=self.buffer_size)
        self.mpu1_ay = deque(maxlen=self.buffer_size)
        self.mpu1_az = deque(maxlen=self.buffer_size)
        self.mpu1_gx = deque(maxlen=self.buffer_size)
        self.mpu1_gy = deque(maxlen=self.buffer_size)
        self.mpu1_gz = deque(maxlen=self.buffer_size)
        self.mpu2_ax = deque(maxlen=self.buffer_size)
        self.mpu2_ay = deque(maxlen=self.buffer_size)
        self.mpu2_az = deque(maxlen=self.buffer_size)
        self.mpu2_gx = deque(maxlen=self.buffer_size)
        self.mpu2_gy = deque(maxlen=self.buffer_size)
        self.mpu2_gz = deque(maxlen=self.buffer_size)
        self.mpu3_ax = deque(maxlen=self.buffer_size)
        self.mpu3_ay = deque(maxlen=self.buffer_size)
        self.mpu3_az = deque(maxlen=self.buffer_size)
        self.mpu3_gx = deque(maxlen=self.buffer_size)
        self.mpu3_gy = deque(maxlen=self.buffer_size)
        self.mpu3_gz = deque(maxlen=self.buffer_size)
        self.mpu4_ax = deque(maxlen=self.buffer_size)
        self.mpu4_ay = deque(maxlen=self.buffer_size)
        self.mpu4_az = deque(maxlen=self.buffer_size)
        self.mpu4_gx = deque(maxlen=self.buffer_size)
        self.mpu4_gy = deque(maxlen=self.buffer_size)
        self.mpu4_gz = deque(maxlen=self.buffer_size)

    def setup_control_panel(self):
        """コントロールパネル設定"""
        control_layout = QHBoxLayout()

        # デバイス選択
        self.device_combo = QComboBox()
        self.scan_btn = QPushButton('Scan BLE')
        self.scan_btn.clicked.connect(self.scan_devices) # Now calls asyncSlot

        # 接続ボタン
        self.connect_btn = QPushButton('Connect')
        self.connect_btn.clicked.connect(self.toggle_connection)

        # LSL接続ボタン
        self.lsl_connect_btn = QPushButton('Connect LSL')
        self.lsl_connect_btn.clicked.connect(self.toggle_lsl_connection)

        # 記録ボタン
        self.record_btn = QPushButton('Start Recording')
        self.record_btn.clicked.connect(self.toggle_recording)

        # 時間窓設定
        self.time_window_spin = QDoubleSpinBox()
        self.time_window_spin.setRange(1, 30)
        self.time_window_spin.setValue(self.time_window)
        self.time_window_spin.valueChanged.connect(self.update_time_window)

        # ステータス
        self.status_label = QLabel('BLE: Disconnected')
        self.status_label.setStyleSheet("color: red")

        self.lsl_status_label = QLabel('LSL: Disconnected')
        self.lsl_status_label.setStyleSheet("color: red")

        # レイアウト追加
        control_layout.addWidget(QLabel('Device:'))
        control_layout.addWidget(self.device_combo)
        control_layout.addWidget(self.scan_btn)
        control_layout.addWidget(self.connect_btn)
        control_layout.addWidget(self.lsl_connect_btn)
        control_layout.addWidget(self.record_btn)
        control_layout.addWidget(QLabel('Window(s):'))
        control_layout.addWidget(self.time_window_spin)
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.lsl_status_label)
        control_layout.addStretch()

        self.layout.addLayout(control_layout)

    def setup_graphs(self):
        """グラフ設定"""
        graph_widget = QWidget()
        graph_layout = QGridLayout(graph_widget)
        
        # ECG1
        self.ecg1_plot = pg.PlotWidget(title='ECG Signal 1')
        self.ecg1_plot.setBackground('w')
        self.ecg1_curve = self.ecg1_plot.plot(pen='r', width=2)
        self.ecg1_plot.showGrid(x=True, y=True)
        
        # ECG2
        self.ecg2_plot = pg.PlotWidget(title='ECG Signal 2')
        self.ecg2_plot.setBackground('w')
        self.ecg2_curve = self.ecg2_plot.plot(pen='b', width=2)
        self.ecg2_plot.showGrid(x=True, y=True)
        
        # MPU1 加速度
        self.mpu1_accel_plot = pg.PlotWidget(title='MPU6050 #1 Acceleration')
        self.mpu1_accel_plot.setBackground('w')
        self.mpu1_ax_curve = self.mpu1_accel_plot.plot(pen='r', name='X', width=2)
        self.mpu1_ay_curve = self.mpu1_accel_plot.plot(pen='g', name='Y', width=2)
        self.mpu1_az_curve = self.mpu1_accel_plot.plot(pen='b', name='Z', width=2)
        self.mpu1_accel_plot.addLegend()
        self.mpu1_accel_plot.showGrid(x=True, y=True)
        
        # MPU2 加速度
        self.mpu2_accel_plot = pg.PlotWidget(title='MPU6050 #2 Acceleration')
        self.mpu2_accel_plot.setBackground('w')
        self.mpu2_ax_curve = self.mpu2_accel_plot.plot(pen='r', name='X', width=2)
        self.mpu2_ay_curve = self.mpu2_accel_plot.plot(pen='g', name='Y', width=2)
        self.mpu2_az_curve = self.mpu2_accel_plot.plot(pen='b', name='Z', width=2)
        self.mpu2_accel_plot.addLegend()
        self.mpu2_accel_plot.showGrid(x=True, y=True)
        
        # MPU1 ジャイロ
        self.mpu1_gyro_plot = pg.PlotWidget(title='MPU6050 #1 Gyroscope')
        self.mpu1_gyro_plot.setBackground('w')
        self.mpu1_gx_curve = self.mpu1_gyro_plot.plot(pen='r', name='X', width=2)
        self.mpu1_gy_curve = self.mpu1_gyro_plot.plot(pen='g', name='Y', width=2)
        self.mpu1_gz_curve = self.mpu1_gyro_plot.plot(pen='b', name='Z', width=2)
        self.mpu1_gyro_plot.addLegend()
        self.mpu1_gyro_plot.showGrid(x=True, y=True)
        
        # MPU2 ジャイロ
        self.mpu2_gyro_plot = pg.PlotWidget(title='MPU6050 #2 Gyroscope')
        self.mpu2_gyro_plot.setBackground('w')
        self.mpu2_gx_curve = self.mpu2_gyro_plot.plot(pen='r', name='X', width=2)
        self.mpu2_gy_curve = self.mpu2_gyro_plot.plot(pen='g', name='Y', width=2)
        self.mpu2_gz_curve = self.mpu2_gyro_plot.plot(pen='b', name='Z', width=2)
        self.mpu2_gyro_plot.addLegend()
        self.mpu2_gyro_plot.showGrid(x=True, y=True)
        
        # MPU3 加速度
        self.mpu3_accel_plot = pg.PlotWidget(title='MPU6050 #3 Acceleration')
        self.mpu3_accel_plot.setBackground('w')
        self.mpu3_ax_curve = self.mpu3_accel_plot.plot(pen='r', name='X', width=2)
        self.mpu3_ay_curve = self.mpu3_accel_plot.plot(pen='g', name='Y', width=2)
        self.mpu3_az_curve = self.mpu3_accel_plot.plot(pen='b', name='Z', width=2)
        self.mpu3_accel_plot.addLegend()
        self.mpu3_accel_plot.showGrid(x=True, y=True)
        
        # MPU4 加速度
        self.mpu4_accel_plot = pg.PlotWidget(title='MPU6050 #4 Acceleration')
        self.mpu4_accel_plot.setBackground('w')
        self.mpu4_ax_curve = self.mpu4_accel_plot.plot(pen='r', name='X', width=2)
        self.mpu4_ay_curve = self.mpu4_accel_plot.plot(pen='g', name='Y', width=2)
        self.mpu4_az_curve = self.mpu4_accel_plot.plot(pen='b', name='Z', width=2)
        self.mpu4_accel_plot.addLegend()
        self.mpu4_accel_plot.showGrid(x=True, y=True)
        
        # MPU3 ジャイロ
        self.mpu3_gyro_plot = pg.PlotWidget(title='MPU6050 #3 Gyroscope')
        self.mpu3_gyro_plot.setBackground('w')
        self.mpu3_gx_curve = self.mpu3_gyro_plot.plot(pen='r', name='X', width=2)
        self.mpu3_gy_curve = self.mpu3_gyro_plot.plot(pen='g', name='Y', width=2)
        self.mpu3_gz_curve = self.mpu3_gyro_plot.plot(pen='b', name='Z', width=2)
        self.mpu3_gyro_plot.addLegend()
        self.mpu3_gyro_plot.showGrid(x=True, y=True)
        
        # MPU4 ジャイロ
        self.mpu4_gyro_plot = pg.PlotWidget(title='MPU6050 #4 Gyroscope')
        self.mpu4_gyro_plot.setBackground('w')
        self.mpu4_gx_curve = self.mpu4_gyro_plot.plot(pen='r', name='X', width=2)
        self.mpu4_gy_curve = self.mpu4_gyro_plot.plot(pen='g', name='Y', width=2)
        self.mpu4_gz_curve = self.mpu4_gyro_plot.plot(pen='b', name='Z', width=2)
        self.mpu4_gyro_plot.addLegend()
        self.mpu4_gyro_plot.showGrid(x=True, y=True)
        
        # レイアウト配置
        graph_layout.addWidget(self.ecg1_plot, 0, 0)
        graph_layout.addWidget(self.ecg2_plot, 0, 1)
        graph_layout.addWidget(self.mpu1_accel_plot, 1, 0)
        graph_layout.addWidget(self.mpu2_accel_plot, 1, 1)
        graph_layout.addWidget(self.mpu3_accel_plot, 1, 2)
        graph_layout.addWidget(self.mpu4_accel_plot, 1, 3)
        graph_layout.addWidget(self.mpu1_gyro_plot, 2, 0)
        graph_layout.addWidget(self.mpu2_gyro_plot, 2, 1)
        graph_layout.addWidget(self.mpu3_gyro_plot, 2, 2)
        graph_layout.addWidget(self.mpu4_gyro_plot, 2, 3)
        
        self.layout.addWidget(graph_widget)

    @asyncSlot()
    async def scan_devices(self):
        """CRITICAL CHANGE: Async scan directly on main thread"""
        if not BLEAK_AVAILABLE:
            QMessageBox.critical(self, 'Error', 'bleak library not installed.\nRun: pip install bleak')
            return
        
        self.device_combo.clear()
        self.device_combo.addItem("Scanning...")
        self.scan_btn.setEnabled(False)
        try:
            devices = await BleakScanner.discover(timeout=5.0)
            
            self.device_combo.clear()
            esp32_found = False
            
            for device in devices:
                if device.name:
                    display_name = f"{device.name} ({device.address})"
                    self.device_combo.addItem(display_name)
                    
                    if "ESP32" in device.name:
                        esp32_found = True
                        self.device_combo.setCurrentText(display_name)
            
            if not esp32_found and devices:
                self.device_combo.setCurrentIndex(0)
            elif not devices:
                self.device_combo.addItem("No BLE devices found")
                
        except Exception as e:
            self.device_combo.clear()
            self.device_combo.addItem(f"Scan failed: {str(e)}")
        finally:
            self.scan_btn.setEnabled(True)

    @asyncSlot()
    async def toggle_connection(self):
        """CRITICAL CHANGE: Async connection management"""
        if not self.ble_worker.running:
            device_text = self.device_combo.currentText()
            if "(" in device_text and ")" in device_text:
                address = device_text.split("(")[1].split(")")[0]
                self.ble_worker.set_device_address(address)
                self.connect_btn.setText('Connecting...')
                self.connect_btn.setEnabled(False)
                
                # Start worker logic as a task
                self.ble_task = asyncio.create_task(self.ble_worker.start())
            else:
                QMessageBox.warning(self, 'Warning', 'Please select a valid BLE device')
        else:
            self.connect_btn.setText('Disconnecting...')
            await self.ble_worker.disconnect()
            if self.ble_task:
                await self.ble_task # Wait for cleanup
            self.connect_btn.setText('Connect')
            self.status_label.setText('Status: Disconnected')
            self.status_label.setStyleSheet("color: red")


    def on_connection_status(self, connected, message):
        """BLE connection status change"""
        if connected:
            self.status_label.setText(f'BLE: {message}')
            self.status_label.setStyleSheet("color: green")
            self.connect_btn.setText('Disconnect')
            self.start_time = None
        else:
            self.status_label.setText(f'BLE: {message}')
            self.status_label.setStyleSheet("color: red")
            self.connect_btn.setText('Connect')

        self.connect_btn.setEnabled(True)

    def toggle_lsl_connection(self):
        """LSL接続切り替え"""
        if not PYLSL_AVAILABLE:
            QMessageBox.critical(self, 'Error', 'pylsl library not installed.\nRun: pip install pylsl')
            return

        if not self.lsl_connected:
            # LSL接続開始
            self.lsl_worker = LSLTriggerWorker()
            self.lsl_worker.trigger_received.connect(self.on_lsl_trigger)
            self.lsl_worker.connection_status.connect(self.on_lsl_connection_status)
            self.lsl_worker.start()
            self.lsl_connect_btn.setText('Connecting...')
            self.lsl_connect_btn.setEnabled(False)
        else:
            # LSL切断
            if self.lsl_worker:
                self.lsl_worker.stop()
                self.lsl_worker = None
            self.lsl_connected = False
            self.lsl_connect_btn.setText('Connect LSL')
            self.lsl_status_label.setText('LSL: Disconnected')
            self.lsl_status_label.setStyleSheet("color: red")

    def on_lsl_connection_status(self, connected, message):
        """LSL接続状態変更"""
        self.lsl_connected = connected
        if connected:
            self.lsl_status_label.setText(f'LSL: Connected')
            self.lsl_status_label.setStyleSheet("color: green")
            self.lsl_connect_btn.setText('Disconnect LSL')
        else:
            self.lsl_status_label.setText(f'LSL: {message}')
            self.lsl_status_label.setStyleSheet("color: red")
            self.lsl_connect_btn.setText('Connect LSL')

        self.lsl_connect_btn.setEnabled(True)

    def on_lsl_trigger(self, trigger, session_dir, output_filename_prefix, run_id, participant_id, session_id, task_long_name):
        """LSL trigger reception processing"""
        if trigger == "START":
            self.current_session_dir = session_dir
            self.current_output_filename_prefix = output_filename_prefix
            self.current_run_id = run_id
            self.current_participant_id = participant_id
            self.current_session_id = session_id
            self.current_task_long_name = task_long_name
            
            # Start recording automatically
            if not self.recording:
                self.start_recording(is_manual_command=False)
        elif trigger == "STOP":
            # Automatically stop recording
            if self.recording:
                self.stop_recording(is_manual_command=False)

    def process_data(self, binary_data):
        """Received data processing (binary format)"""
        data = self.parse_binary_data(binary_data)
        if data:
            current_time = data['timestamp'] / 1e6 # number of seconds passed since January 1, 1970

            if self.start_time is None: # start time signal the time the dispositive started sending data, it is used inside the graphs, it remains the same until the app is closed or the sensor is disconnected
                self.start_time = current_time

            if self.recording:
                if self.acq_time is None:
                    self.acq_time = current_time # acq time is when the run started, it is used for calculating the timestamp inisde tsv files, it gets resetted at each new run
                    self.acq_time_correct = datetime.now().isoformat()
                relative_time_in_tsv = current_time - self.acq_time
            
            relative_time_in_graph = current_time - self.start_time

            # MPUデータの更新
            if data['has_mpu']:
                self.last_mpu_data = {
                    'mpu1_ax': data['mpu1_ax'], 'mpu1_ay': data['mpu1_ay'], 'mpu1_az': data['mpu1_az'],
                    'mpu1_gx': data['mpu1_gx'], 'mpu1_gy': data['mpu1_gy'], 'mpu1_gz': data['mpu1_gz'],
                    'mpu2_ax': data['mpu2_ax'], 'mpu2_ay': data['mpu2_ay'], 'mpu2_az': data['mpu2_az'],
                    'mpu2_gx': data['mpu2_gx'], 'mpu2_gy': data['mpu2_gy'], 'mpu2_gz': data['mpu2_gz'],
                    'mpu3_ax': data['mpu3_ax'], 'mpu3_ay': data['mpu3_ay'], 'mpu3_az': data['mpu3_az'],
                    'mpu3_gx': data['mpu3_gx'], 'mpu3_gy': data['mpu3_gy'], 'mpu3_gz': data['mpu3_gz'],
                    'mpu4_ax': data['mpu4_ax'], 'mpu4_ay': data['mpu4_ay'], 'mpu4_az': data['mpu4_az'],
                    'mpu4_gx': data['mpu4_gx'], 'mpu4_gy': data['mpu4_gy'], 'mpu4_gz': data['mpu4_gz']
                }

            # Use last MPU data (0 if not)
            mpu_data = self.last_mpu_data if self.last_mpu_data else {
                'mpu1_ax': 0, 'mpu1_ay': 0, 'mpu1_az': 0, 'mpu1_gx': 0, 'mpu1_gy': 0, 'mpu1_gz': 0,
                'mpu2_ax': 0, 'mpu2_ay': 0, 'mpu2_az': 0, 'mpu2_gx': 0, 'mpu2_gy': 0, 'mpu2_gz': 0,
                'mpu3_ax': 0, 'mpu3_ay': 0, 'mpu3_az': 0, 'mpu3_gx': 0, 'mpu3_gy': 0, 'mpu3_gz': 0,
                'mpu4_ax': 0, 'mpu4_ay': 0, 'mpu4_az': 0, 'mpu4_gx': 0, 'mpu4_gy': 0, 'mpu4_gz': 0
            }

            # add to buffer
            self.timestamps.append(relative_time_in_graph)
            self.ecg1_data.append(data['ecg1'])
            self.ecg2_data.append(data['ecg2'])
            self.mpu1_ax.append(mpu_data['mpu1_ax'])
            self.mpu1_ay.append(mpu_data['mpu1_ay'])
            self.mpu1_az.append(mpu_data['mpu1_az'])
            self.mpu1_gx.append(mpu_data['mpu1_gx'])
            self.mpu1_gy.append(mpu_data['mpu1_gy'])
            self.mpu1_gz.append(mpu_data['mpu1_gz'])
            self.mpu2_ax.append(mpu_data['mpu2_ax'])
            self.mpu2_ay.append(mpu_data['mpu2_ay'])
            self.mpu2_az.append(mpu_data['mpu2_az'])
            self.mpu2_gx.append(mpu_data['mpu2_gx'])
            self.mpu2_gy.append(mpu_data['mpu2_gy'])
            self.mpu2_gz.append(mpu_data['mpu2_gz'])
            self.mpu3_ax.append(mpu_data['mpu3_ax'])
            self.mpu3_ay.append(mpu_data['mpu3_ay'])
            self.mpu3_az.append(mpu_data['mpu3_az'])
            self.mpu3_gx.append(mpu_data['mpu3_gx'])
            self.mpu3_gy.append(mpu_data['mpu3_gy'])
            self.mpu3_gz.append(mpu_data['mpu3_gz'])
            self.mpu4_ax.append(mpu_data['mpu4_ax'])
            self.mpu4_ay.append(mpu_data['mpu4_ay'])
            self.mpu4_az.append(mpu_data['mpu4_az'])
            self.mpu4_gx.append(mpu_data['mpu4_gx'])
            self.mpu4_gy.append(mpu_data['mpu4_gy'])
            self.mpu4_gz.append(mpu_data['mpu4_gz'])

            # TSV記録
            if self.recording:
                if self.tsv_file_ecg:
                    self.tsv_writer_ecg.writerow([relative_time_in_tsv, data['ecg1'], data['ecg2']])
                if self.tsv_file_mpu and self.data_counter == 0:
                    self.tsv_writer_mpu.writerow([relative_time_in_tsv, 
                                        mpu_data['mpu1_ax'], mpu_data['mpu1_ay'], mpu_data['mpu1_az'],
                                        mpu_data['mpu1_gx'], mpu_data['mpu1_gy'], mpu_data['mpu1_gz'],
                                        mpu_data['mpu2_ax'], mpu_data['mpu2_ay'], mpu_data['mpu2_az'],
                                        mpu_data['mpu2_gx'], mpu_data['mpu2_gy'], mpu_data['mpu2_gz'],
                                        mpu_data['mpu3_ax'], mpu_data['mpu3_ay'], mpu_data['mpu3_az'],
                                        mpu_data['mpu3_gx'], mpu_data['mpu3_gy'], mpu_data['mpu3_gz'],
                                        mpu_data['mpu4_ax'], mpu_data['mpu4_ay'], mpu_data['mpu4_az'],
                                        mpu_data['mpu4_gx'], mpu_data['mpu4_gy'], mpu_data['mpu4_gz']])
            if self.data_counter > 1:
                self.data_counter = 0
            else:
                self.data_counter += 1 # TODO try by keeping it always 0 and then see if 3 entry are the same

    def parse_binary_data(self, binary_data):
        """binary data parsing"""
        try:
            if len(binary_data) < 9:
                return None

            idx = 0
            # フラグ
            flag = binary_data[idx]
            idx += 1
            has_mpu = (flag & 0x01) != 0

            # ECG (uint16 x 2)
            ecg1 = struct.unpack('<H', binary_data[idx:idx+2])[0]
            idx += 2
            ecg2 = struct.unpack('<H', binary_data[idx:idx+2])[0]
            idx += 2

            # タイムスタンプ (uint32)
            timestamp = struct.unpack('<I', binary_data[idx:idx+4])[0]
            idx += 4

            result = {
                'ecg1': ecg1,
                'ecg2': ecg2,
                'timestamp': timestamp,
                'has_mpu': has_mpu,
                'mpu1_ax': 0, 'mpu1_ay': 0, 'mpu1_az': 0,
                'mpu1_gx': 0, 'mpu1_gy': 0, 'mpu1_gz': 0,
                'mpu2_ax': 0, 'mpu2_ay': 0, 'mpu2_az': 0,
                'mpu2_gx': 0, 'mpu2_gy': 0, 'mpu2_gz': 0,
                'mpu3_ax': 0, 'mpu3_ay': 0, 'mpu3_az': 0,
                'mpu3_gx': 0, 'mpu3_gy': 0, 'mpu3_gz': 0,
                'mpu4_ax': 0, 'mpu4_ay': 0, 'mpu4_az': 0,
                'mpu4_gx': 0, 'mpu4_gy': 0, 'mpu4_gz': 0
            }

            # MPUデータ (int16 x 24, 100倍されている)
            if has_mpu and len(binary_data) >= idx + 48:
                mpu_values = struct.unpack('<24h', binary_data[idx:idx+48])
                result.update({
                    'mpu1_ax': mpu_values[0] / 100.0, 'mpu1_ay': mpu_values[1] / 100.0, 'mpu1_az': mpu_values[2] / 100.0,
                    'mpu1_gx': mpu_values[3] / 100.0, 'mpu1_gy': mpu_values[4] / 100.0, 'mpu1_gz': mpu_values[5] / 100.0,
                    'mpu2_ax': mpu_values[6] / 100.0, 'mpu2_ay': mpu_values[7] / 100.0, 'mpu2_az': mpu_values[8] / 100.0,
                    'mpu2_gx': mpu_values[9] / 100.0, 'mpu2_gy': mpu_values[10] / 100.0, 'mpu2_gz': mpu_values[11] / 100.0,
                    'mpu3_ax': mpu_values[12] / 100.0, 'mpu3_ay': mpu_values[13] / 100.0, 'mpu3_az': mpu_values[14] / 100.0,
                    'mpu3_gx': mpu_values[15] / 100.0, 'mpu3_gy': mpu_values[16] / 100.0, 'mpu3_gz': mpu_values[17] / 100.0,
                    'mpu4_ax': mpu_values[18] / 100.0, 'mpu4_ay': mpu_values[19] / 100.0, 'mpu4_az': mpu_values[20] / 100.0,
                    'mpu4_gx': mpu_values[21] / 100.0, 'mpu4_gy': mpu_values[22] / 100.0, 'mpu4_gz': mpu_values[23] / 100.0
                })

            return result
        except Exception as e:
            print(f"Binary parse error: {e}")
            return None

    def update_time_window(self, value):
        """時間窓更新"""
        self.time_window = value
        self.buffer_size = int(300 * value)
        self.init_data_buffers()



    def toggle_recording(self):
        # in both cases the argument lsl_trigger received is false since is manual command
        if self.toggle_is_start: # this means that the start button was not pressed before this moment
            self.start_recording(is_manual_command=True)
        else:
            self.stop_recording(is_manual_command=True)



    def start_recording(self, is_manual_command: bool):
        """Recording start (from LSL trigger if lsl_trigger_received == True)"""
        if self.recording: # ignore the command if already recording
            return
        try:
            if is_manual_command:
                # if the recording started manually just save both files in the current directory
                file_path_ecg = f'esp32_ble_sensor_{datetime.now().strftime("%Y%m%d_%H%M%S")}_recording-ecg_physio.tsv.gz'
                file_path_mpu = f'esp32_ble_sensor_{datetime.now().strftime("%Y%m%d_%H%M%S")}_tracksys-mpu_motion.tsv'
            else:
                output_dir_ecg = Path(self.current_session_dir) / "physio"
                output_dir_mpu = Path(self.current_session_dir) / "motion"
                # Create directories
                output_dir_ecg.mkdir(parents=True, exist_ok=True)
                output_dir_mpu.mkdir(parents=True, exist_ok=True)
                # File names generation (BIDS format style)
                file_path_ecg = output_dir_ecg / f"{self.current_output_filename_prefix}_{self.current_run_id}_recording-ecg_physio.tsv.gz"
                file_path_mpu = output_dir_mpu / f"{self.current_output_filename_prefix}_tracksys-mpu_{self.current_run_id}_motion.tsv"
            
            # in both cases, manual or LSL, proceed with tsv files creation
            # physio file must be tsv.gz, open it using gzip
            self.tsv_file_ecg = gzip.open(file_path_ecg, 'wt', newline='')
            self.tsv_writer_ecg = csv.writer(self.tsv_file_ecg, delimiter='\t')
            # motions file must be tsv
            self.tsv_file_mpu = open(file_path_mpu, 'wt', newline='')
            self.tsv_writer_mpu = csv.writer(self.tsv_file_mpu, delimiter='\t')
            
            # TODO here create the file channels.tsv

            self.recording = True # only after having opening the files we are ready to record on them
            
            if is_manual_command:
                # change the button to stop recording
                self.toggle_is_start = False
                self.record_btn.setText('Stop Recording')
                # print that the recording has started
                print(f"📝 Manual recording started: {file_path_ecg}, {file_path_mpu}")
                QMessageBox.information(self, 'Manual Recording Started', f'Recording to:\n{file_path_ecg}\n{file_path_mpu}')
            else:
                self.record_btn.setEnabled(False)  # Manual start/stop is not possible during LSL control, so disable the start/stop button
                print(f"✅ LSL Recording started: {file_path_ecg}, {file_path_mpu}")
                QMessageBox.information(self, 'LSL Recording Started', f'Recording to:\n{file_path_ecg}\n{file_path_mpu}')

        except Exception as e:
            error_msg = f'Failed to start recording: {str(e)}'
            print(f"❌ {error_msg}")
            QMessageBox.critical(self, 'Error', error_msg)



    def stop_recording(self, is_manual_command: bool):
        """Recording stop (from LSL trigger)"""
        if not self.recording: # ignore the command if already not recording
            return
        try:
            if self.tsv_file_ecg:
                file_path_ecg = self.tsv_file_ecg.name
                self.tsv_file_ecg.close()
                self.tsv_file_ecg = None
                print(f"✅ Recording stopped: {file_path_ecg}")
                if not is_manual_command:
                    # determine and save the scans metadata file
                    scans_list = [{
                        'file_path': Path(file_path_ecg),
                        'acq_time': self.acq_time_correct
                    }]
                    dataset_utils.write_on_scans_tsv(self.current_participant_id, self.current_session_id, scans_list)
            if self.tsv_file_mpu:
                file_path_mpu = self.tsv_file_mpu.name
                self.tsv_file_mpu.close()
                self.tsv_file_mpu = None
                print(f"✅ Recording stopped: {file_path_mpu}")
                if not is_manual_command:
                    # determine and save the scans metadata file
                    scans_list = [{
                        'file_path': Path(file_path_mpu),
                        'acq_time': self.acq_time_correct
                    }]
                    dataset_utils.write_on_scans_tsv(self.current_participant_id, self.current_session_id, scans_list)

            if not is_manual_command:
                QMessageBox.information(self, 'Recording Stopped', f'Data saved in:\n{file_path_ecg}\n{file_path_mpu}\nScans saved in folder: {Path(self.current_session_dir)}')
            else:
                QMessageBox.information(self, 'Recording Stopped', f'Data saved in:\n{file_path_ecg}\n{file_path_mpu}')
            
            self.acq_time = None # reset the acquisition time for the next run
            self.recording = False
            # show start recording again on the start/stop button
            if is_manual_command:
                self.toggle_is_start = True
                self.record_btn.setText('Start Recording')
            self.record_btn.setEnabled(True)  # Re-enable manual button

        except Exception as e:
            error_msg = f'Failed to stop auto recording: {str(e)}'
            print(f"❌ {error_msg}")
            QMessageBox.critical(self, 'Error', error_msg)

    def update_plot(self):
        """グラフ更新"""
        if len(self.timestamps) > 0:
            time_data = list(self.timestamps)
            
            # 各グラフ更新
            self.ecg1_curve.setData(time_data, list(self.ecg1_data))
            self.ecg2_curve.setData(time_data, list(self.ecg2_data))
            
            self.mpu1_ax_curve.setData(time_data, list(self.mpu1_ax))
            self.mpu1_ay_curve.setData(time_data, list(self.mpu1_ay))
            self.mpu1_az_curve.setData(time_data, list(self.mpu1_az))
            
            self.mpu2_ax_curve.setData(time_data, list(self.mpu2_ax))
            self.mpu2_ay_curve.setData(time_data, list(self.mpu2_ay))
            self.mpu2_az_curve.setData(time_data, list(self.mpu2_az))
            
            self.mpu3_ax_curve.setData(time_data, list(self.mpu3_ax))
            self.mpu3_ay_curve.setData(time_data, list(self.mpu3_ay))
            self.mpu3_az_curve.setData(time_data, list(self.mpu3_az))
            
            self.mpu4_ax_curve.setData(time_data, list(self.mpu4_ax))
            self.mpu4_ay_curve.setData(time_data, list(self.mpu4_ay))
            self.mpu4_az_curve.setData(time_data, list(self.mpu4_az))
            
            self.mpu1_gx_curve.setData(time_data, list(self.mpu1_gx))
            self.mpu1_gy_curve.setData(time_data, list(self.mpu1_gy))
            self.mpu1_gz_curve.setData(time_data, list(self.mpu1_gz))
            
            self.mpu2_gx_curve.setData(time_data, list(self.mpu2_gx))
            self.mpu2_gy_curve.setData(time_data, list(self.mpu2_gy))
            self.mpu2_gz_curve.setData(time_data, list(self.mpu2_gz))
            
            self.mpu3_gx_curve.setData(time_data, list(self.mpu3_gx))
            self.mpu3_gy_curve.setData(time_data, list(self.mpu3_gy))
            self.mpu3_gz_curve.setData(time_data, list(self.mpu3_gz))
            
            self.mpu4_gx_curve.setData(time_data, list(self.mpu4_gx))
            self.mpu4_gy_curve.setData(time_data, list(self.mpu4_gy))
            self.mpu4_gz_curve.setData(time_data, list(self.mpu4_gz))
            
            # X-axis range adjustment
            if time_data:
                current_time = time_data[-1]
                x_min = max(0, current_time - self.time_window)
                x_max = current_time + 0.5
                
                for plot in [self.ecg1_plot, self.ecg2_plot, self.mpu1_accel_plot, 
                           self.mpu2_accel_plot, self.mpu3_accel_plot, self.mpu4_accel_plot,
                           self.mpu1_gyro_plot, self.mpu2_gyro_plot, self.mpu3_gyro_plot, self.mpu4_gyro_plot]:
                    plot.setXRange(x_min, x_max)

    def closeEvent(self, event):
        """Application termination process"""
        asyncio.create_task(self.cleanup())
        if self.lsl_worker:
            self.lsl_worker.stop()
        if self.tsv_file_ecg:
            self.tsv_file_ecg.close()
        if self.tsv_file_mpu:
            self.tsv_file_mpu.close()
        event.accept()
    
    async def cleanup(self):
        if self.ble_worker: await self.ble_worker.disconnect()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # 依存ライブラリチェック
    missing_libs = []
    if not BLEAK_AVAILABLE:
        missing_libs.append('bleak')
    if not PYLSL_AVAILABLE:
        missing_libs.append('pylsl')

    if missing_libs:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle('Missing Dependencies')
        msg.setText('Some libraries are not installed!')
        msg.setInformativeText(f'Please install: pip install {" ".join(missing_libs)}\n\n'
                              'The application will start, but some features may not work.')
        msg.exec_()
        if not BLEAK_AVAILABLE:
            # BLEが無い場合は起動しない
            sys.exit(1)

    # CRITICAL PART CHANGE: Event loop setup
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    window = ESP32BLESensorVisualizer()
    window.show()
    
    with loop:
        loop.run_forever()