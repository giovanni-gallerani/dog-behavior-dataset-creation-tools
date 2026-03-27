# package used to see which operative system is being used
import sys

# packages for GUI
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from PIL import Image, ImageTk

# package for path names
from pathlib import Path

# package for LSL connection
from pylsl import StreamInlet, resolve_byprop

# packages for video and audio recording + metadata
import cv2
import sounddevice as sd
import soundfile as sf
import threading
import queue
import subprocess
import time
from datetime import datetime
import csv

# this import is necessary to reduce the time for camera activation, do not edit it
import os
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

import dataset_utils


# Each computer must have a different CAMERA_ID in each camera.
# When using more than 1 computer, the IDs must be unique also among different computers
# otherwise different files with the same name will be created on different computers

# examples of output files:
# cam-1_audio.wav
# cam-1_video.mp4
# sub-01_pres-01_cam-1.mp4 (merge of the first 2, the first 2 gets deleted after the merge)
# sub-01_pres-01_dog-neck-mic.wav

# ============================================================
# Recording Devices Settings
# ============================================================
if True:
    # LEFT PC
    LEFT_CAMERA_ID = 1
    LEFT_CAMERA_VIDEO_IDX = 2
    LEFT_CAMERA_AUDIO_IDX = 3

    RIGHT_CAMERA_ID = 2
    RIGHT_CAMERA_VIDEO_IDX = 0
    RIGHT_CAMERA_AUDIO_IDX = 4

    DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC = True
    DOG_NECK_MICROPHONE_AUDIO_IDX = 1

    OWNER_MICROPHONE_CONNECTED_TO_THIS_PC = False
    OWNER_MICROPHONE_AUDIO_IDX = 1
else:
    # RIGHT PC
    LEFT_CAMERA_ID = 3
    LEFT_CAMERA_VIDEO_IDX = 0
    LEFT_CAMERA_AUDIO_IDX = 3

    RIGHT_CAMERA_ID = 4
    RIGHT_CAMERA_VIDEO_IDX = 2
    RIGHT_CAMERA_AUDIO_IDX = 4

    DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC = False
    DOG_NECK_MICROPHONE_AUDIO_IDX = 1

    OWNER_MICROPHONE_CONNECTED_TO_THIS_PC = True
    OWNER_MICROPHONE_AUDIO_IDX = 1

# ============================================================
# Metadata Files Settings
# ============================================================
# commented out since I'm planning to calculate it after the creation of the dataset
# WRITE_SESSIONS_METADATA_ON_PC = True # write the name of each recording session in a tsv file, later a acq_time column can be added by using the acq_time of all the files in that session
# scans metadata always gets written in the output directory

# ============================================================
# Cameras Output Files Settings
# ============================================================
DELETE_CAMERA_AUDIO_AND_VIDEO_ONLY_FILES_AFTER_MERGE = True

# temporary files created during the recording session, they will be deleted after merging audio and video
LEFT_CAMERA_VIDEO_FILENAME = f"temp_recording-cam{LEFT_CAMERA_ID}_video.mp4"
LEFT_CAMERA_AUDIO_FILENAME = f"temp_recording-cam{LEFT_CAMERA_ID}_audio.wav"
RIGHT_CAMERA_VIDEO_FILENAME = f"temp_recording-cam{RIGHT_CAMERA_ID}_video.mp4"
RIGHT_CAMERA_AUDIO_FILENAME = f"temp_recording-cam{RIGHT_CAMERA_ID}_audio.wav"

def get_camera_merged_output_filename(output_filename_prefix: str, run_id: str, camera_id: int) -> str:
    return f"{output_filename_prefix}_{run_id}_recording-cam{camera_id}_video.mp4"

# ============================================================
# Wireless Microphones Output Files Settings
# ============================================================
def get_dog_microphone_output_filename(output_filename_prefix: str, run_id: str) -> str:
    return f"{output_filename_prefix}_{run_id}_recording-micdog_audio.wav"

def get_owner_microphone_output_filename(output_filename_prefix: str, run_id: str) -> str:
    return f"{output_filename_prefix}_{run_id}_recording-micowner_audio.wav"

# ============================================================
# Video Quality Settings
# ============================================================
VIDEO_WIDTH  = 1920
VIDEO_HEIGHT = 1080
VIDEO_BUFFERSIZE = 10
VIDEO_FPS = 30
VIDEO_RECORD_QUEUE_MAXSIZE = 1000 # how many frames can get stored in the recording queue while waiting to write them

# ============================================================
# Audio Quality Settings
# ============================================================
AUDIO_SAMPLERATE = 44100
AUDIO_CHANNELS = 1
AUDIO_RECORD_QUEUE_MAXSIZE = 1000 # how many elements can get stored in the recording queue while waiting to write them

# ============================================================
# Lab Streaming Layer Connection Settings
# ============================================================
LSL_RECORDING_TRIGGER_STREAM_NAME = "RecordingTrigger" # name to search for in the LSL network
LSL_WAITING_COMMANDER_TIMEOUT_SEC = 1
LSL_CONNECTION_STATE_LABEL_REFRESH_PERIOD_MS = LSL_WAITING_COMMANDER_TIMEOUT_SEC * 1000

# ============================================================
# Video Previews Settings
# ============================================================
VIDEO_PREVIEW_WIDTH = 640
VIDEO_PREVIEW_LENGTH = 360
VIDEO_PREVIEW_REFRESH_PERIOD_MS = 10

##############################################################

# ============================================================
# Camera Reader and Recorder - read frames and put them in the queues
# preview_queue: used for displaying the preview in the GUI, contains one frame at a time for efficiency
# record_queue: used internally for recording video, can contain multiple frames at a time to minimize frame loss
# ============================================================
class CameraReaderAndRecorder:
    def __init__(self, cap: cv2.VideoCapture):
        self.cap = cap
        self.is_reading = False
        self.is_recording = False
        self.preview_queue = queue.Queue(maxsize=1) # stores 1 frame at a time used for preview in the gui
        self.record_queue = queue.Queue(maxsize=VIDEO_RECORD_QUEUE_MAXSIZE) # stores frame for recording
        self.update_queues_thread = None # thread for updating both queues, active when is_running = True
        self.record_video_thread = None # uses the record queue from the previous thread to save a video


    def start_reading(self):
        if self.is_reading:
            raise Exception("Cannot start multiple reads. Call stop_reading before.")
        self.is_reading = True
        self.update_queues_thread = threading.Thread(target=self._update_queues, daemon=True)
        self.update_queues_thread.start()


    # PRODUCER THREAD
    def _update_queues(self):
        while self.is_reading:
            ret, frame = self.cap.read()
            if ret:
                # Put the frame in preview queue to be used in the GUI
                # If there is already a frame it means that the GUI is busy, the new frame is skipped from the preview
                if self.preview_queue.empty():
                    self.preview_queue.put(frame)
                # If recording, put the frame also in the record queue.
                if self.is_recording and (not self.record_queue.full()):
                    self.record_queue.put(frame)
                else:
                    try:
                        # if the record queue is full remove the oldest frame and add a new one
                        self.record_queue.get_nowait()
                        self.record_queue.put(frame)
                    except:
                        pass            
            else:
                time.sleep(0.005) # Brief sleep if camera disconnects to avoid CPU spike


    def start_recording(self, output_file, video_width, video_heigth, fps):
        """Start recording video to output_file, return the acquisition time (acq_time)"""
        if self.is_recording:
            raise Exception("Cannot start multiple recordings. Call stop_recording before.")
        if not self.is_reading:
            raise Exception("Cannot start recording if not reading frames. Call start_reading before.")
        self.is_recording = True

        # after changing is_recording to True the recording queue starts to be filled, this time is the acquisition time of the video
        # for acq_time is meant the moment in which the first frame is recorded
        acq_time = datetime.now().isoformat()
        self.record_video_thread = threading.Thread(
            target=self._record_video, 
            args=(output_file, video_width, video_heigth, fps), 
            daemon=True
        )
        self.record_video_thread.start()
        return acq_time


    # CONSUMER THREAD
    def _record_video(self, output_file, video_width, video_height, fps):
        command = [
            'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-s', f'{video_width}x{video_height}', '-pix_fmt', 'bgr24',
            '-r', str(fps), '-i', '-',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-pix_fmt', 'yuv420p', output_file
        ]
        frames_written = 0
        start_time = 0
        elapsed_time = 0

        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, 
                                     stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            # Time is measured here so that only the time of frame recording is considered
            print(f"[{output_file}] Started writing file")
            start_time = time.time()
            while self.is_recording or (not self.record_queue.empty()): # when recording or if some frames are still in the record queue
                frame = self.record_queue.get()
                # if frame is None it means that stop_recording have put it in the queue, so exit from the loop
                if frame is None:
                    break
            
                try:
                    process.stdin.write(frame.tobytes())
                    frames_written += 1
                except BrokenPipeError:
                    print("Broken pipe error occurred! Interrupting recording")
                    self.stop_recording()
                    break
            # Calculate time
            elapsed_time = time.time() - start_time
            process.stdin.close()
            process.wait()

        except Exception as e:
            print(f"Error while recording [{output_file}]: {e}")
            self.stop_recording()
            # Calculate the measured fps before exception
            elapsed_time = time.time() - start_time
                 
        measured_fps = frames_written / elapsed_time if elapsed_time > 0 else fps
        print(f"[{output_file}] Recording finished: {frames_written} frames ({measured_fps:.2f} fps)")
    

    def get_preview_frame(self):
        """
        obtain a frame from preview queue, used for showing previews on the gui
        do not use this to save videos since the preview queue does not care about frame loss
        """
        try:
            return self.preview_queue.get()
        except queue.Empty:
            return None
    

    def stop_reading(self):
        if not self.is_reading:
            raise Exception("Reading already stopped, cannot be stopped multiple times.")
        if self.is_recording:
            raise Exception("Cannot stop reading while recording. Call stop_recording before.")
        self.is_reading = False
    

    def stop_recording(self):
        "stop recording and return the recording thread, so that the main thread can wait for it to end"
        if self.is_recording == False:
            raise Exception("Recording already stopped, cannot be stopped multiple times.")
        self.is_recording = False
        # put a sentinel signal, when _record_video will read None it will know that the recording must stop
        self.record_queue.put(None)
        return self.record_video_thread


# ============================================================
# Audio Recorder
# ============================================================
class AudioRecorder:
    def __init__(self, audio_device_index: int):
        self.audio_device_index = audio_device_index
        self.record_queue = queue.Queue(maxsize=AUDIO_RECORD_QUEUE_MAXSIZE)
        self.is_recording = False
        self.thread = None


    def start_recording(self, output_file, samplerate=44100, channels=1):
        """Start recording audio to output_file, return the acquisition time (acq_time)"""
        if self.is_recording:
            raise Exception("Cannot start multiple audio recording on the same AudioRecorder. Stop recording before starting a new one")
        self.is_recording = True
        self.thread = threading.Thread(target=self._record_audio, args=(output_file, samplerate, channels), daemon=True)
        self.thread.start()
        acq_time = datetime.now().isoformat()
        return acq_time
    

    def _callback(self, indata, frames, time, status):
        if status:
            print(status)
        self.record_queue.put(indata.copy())


    def _record_audio(self, output_file, samplerate, channels):
        with sf.SoundFile(output_file, mode='x', samplerate=samplerate, channels=channels) as file:
            with sd.InputStream(samplerate=samplerate, device=self.audio_device_index, 
                              channels=channels, callback=self._callback):
                print(f"[{output_file}] Started writing file")
                while self.is_recording or (not self.record_queue.empty()):
                    data = self.record_queue.get()
                    # if data is None it means that stop_recording have put it in the queue, so exit from the loop
                    if data is None:
                        break
                    file.write(data)
        print(f"[{output_file}] Recording finished")


    def stop_recording(self):
        if self.is_recording == False:
            raise Exception("Recording already stopped, cannot be stopped multiple times")
        self.is_recording = False
        # put a sentinel signal, when _record_audio will read None it will know that the recording must stop
        self.record_queue.put(None)
        return self.thread  # self thread is returned so that the daemon processes can be joined while stopping the recording


# =========================================================
# Merge solo audio and solo video files in video file with audio
# =========================================================
def merge_video_and_audio(output_file_path, video_file_path, audio_file_path):
    if not os.path.exists(video_file_path) or not os.path.exists(audio_file_path):
        print("Error! Video and audio files are not present, impossible to realize merge!")
    
    command = [
        'ffmpeg', '-nostdin', '-y', '-i', video_file_path, '-i', audio_file_path,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-shortest', output_file_path
    ]
    
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
    except Exception as e:
        print(f"Error: Audio merge failed: {e}")
        raise e
    

# ============================================================
# Simple LSL Recorder
# ============================================================
# This is a recorder created for this project, it does not use LabRecorder (hence the name simple).
# The reason for this is efficiency, the data produced are HD video, too heavy to stream them on our lab network.
class SimpleLSLRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Simple LSL Video and Audio Recorder")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.is_reading_frames = False # used to understand if is necessary to stop readings from CameraReaderAndRecorder before closing the app
        self.is_recording = False # used to understand if the recordings have been stopped with a STOP signal before closing the app
        self.is_busy = False # used to refuse new starting signal when the application is saving files or merging audio and video after recording

        # These variables change every time a new session starts, so all of them start with ses_

        # temporary files created during the run
        self.run_temp_file_paths = {
            "left_camera_video": None,
            "left_camera_audio": None,
            "right_camera_video": None,
            "right_camera_audio": None,
        }
        # final output files that remain in the output directory after the end of the run
        self.run_output_file_paths = {
            "left_camera_merged": None,
            "right_camera_merged": None,
            "dog_neck_microphone_audio": None,
            "owner_microphone_audio": None
        }
        # determined by the commander at each run
        self.run_session_dir = None
        self.run_output_filename_prefix = None
        self.run_id = None
        self.run_participant_id = None
        self.run_session_id = None
        self.run_task_long_name = None        

        # calculated by the recording app
        self.run_acq_time = None
        self.run_output_dir_video = None
        self.run_output_dir_audio = None

        # Start initialization process
        print("Initializing devices...")
        print(f"Camera {LEFT_CAMERA_ID} (left):")
        print(f"    Video idx: {LEFT_CAMERA_VIDEO_IDX}")
        print(f"    Audio idx: {LEFT_CAMERA_AUDIO_IDX}")
        print(f"Camera {RIGHT_CAMERA_ID} (right):")
        print(f"    Video idx: {RIGHT_CAMERA_VIDEO_IDX}")
        print(f"    Audio idx: {RIGHT_CAMERA_AUDIO_IDX}")
        if DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC:
            print("Dog neck microphone:")
            print(f"    Audio idx: {DOG_NECK_MICROPHONE_AUDIO_IDX}")
        if OWNER_MICROPHONE_CONNECTED_TO_THIS_PC:
            print("Owner microphone:")
            print(f"    Audio idx: {OWNER_MICROPHONE_AUDIO_IDX}")

        # Prepare classes for audio recording
        self.left_camera_audio_recorder = AudioRecorder(LEFT_CAMERA_AUDIO_IDX)
        self.right_camera_audio_recorder = AudioRecorder(RIGHT_CAMERA_AUDIO_IDX)
        if DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC:
            self.dog_neck_microphone_audio_recorder = AudioRecorder(DOG_NECK_MICROPHONE_AUDIO_IDX)
        if OWNER_MICROPHONE_CONNECTED_TO_THIS_PC:
            self.owner_microphone_audio_recorder = AudioRecorder(OWNER_MICROPHONE_AUDIO_IDX)

        # Open left and right camera video capture
        if sys.platform == "win32":
            self.cap1 = cv2.VideoCapture(LEFT_CAMERA_VIDEO_IDX, cv2.CAP_MSMF)
            self.cap2 = cv2.VideoCapture(RIGHT_CAMERA_VIDEO_IDX, cv2.CAP_MSMF)
        else:
            self.cap1 = cv2.VideoCapture(LEFT_CAMERA_VIDEO_IDX)
            self.cap2 = cv2.VideoCapture(RIGHT_CAMERA_VIDEO_IDX)
        
        # Check if cameras are opened, if not close the application
        camera_not_open_error_msg = []
        if not self.cap1.isOpened():
            camera_not_open_error_msg.append(f"❌ Could not open Camera {LEFT_CAMERA_ID} (left)")
        if not self.cap2.isOpened():
            camera_not_open_error_msg.append(f"❌ Could not open Camera {RIGHT_CAMERA_ID} (right)")
        if camera_not_open_error_msg:
            print("\n".join(camera_not_open_error_msg))
            self.on_closing() # close the app if one or both camera are unavailable
        
        # Set camera properties
        self.set_video_capture_properties(self.cap1, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS, VIDEO_BUFFERSIZE)
        self.set_video_capture_properties(self.cap2, VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS, VIDEO_BUFFERSIZE)
        time.sleep(0.5) # wait in order to be sure that the changes to camera settings have been applied
        
        # cameras are ready, print cameras info on terminal (useful for debugging)
        print("="*40)
        print("✅ Cameras ready")
        print(f"Camera {LEFT_CAMERA_ID} (left)")
        print(f"    buffer size = {self.cap1.get(cv2.CAP_PROP_BUFFERSIZE)}")
        print(f"    resolution = {self.get_resolution(self.cap1)}")
        print(f"    camera fps = {self.cap1.get(cv2.CAP_PROP_FPS)}")
        print(f"Camera {RIGHT_CAMERA_ID} (right)")
        print(f"    buffer size = {self.cap2.get(cv2.CAP_PROP_BUFFERSIZE)}")
        print(f"    resolution = {self.get_resolution(self.cap2)}")
        print(f"    camera fps = {self.cap2.get(cv2.CAP_PROP_FPS)}")
        print("="*40)

        # prepare the queues that will be used for displaying previews and recording videos
        self.left_camera_reader_and_rec = CameraReaderAndRecorder(self.cap1)
        self.right_camera_reader_and_rec = CameraReaderAndRecorder(self.cap2)

        # start reading from the cameras
        self.left_camera_reader_and_rec.start_reading()
        self.right_camera_reader_and_rec.start_reading()
        self.is_reading_frames = True # signal that the state has changed, now the app started reading frames from the cameras
        
        # --- GUI ELEMENTS ---
        self.init_gui()

        # show the video previews on the screen using the frames collected by the reading frames threads
        self.update_video_previews()
        
        self.log("📡 Waiting for LSL trigger")
        self.log(f"🔍 Looking for LSL stream '{LSL_RECORDING_TRIGGER_STREAM_NAME}'...")
        # use a thread for searching for LSL conncetion and initializing the inlet
        self.inlet_info = None # used for storing the  informations regarding the inlet stream
        self.inlet = None # used for connecting to LSL
        self.search_for_commander = True # variable used for terminating the following thread
        self.create_connection_lsl_stream_thread = threading.Thread(target=self._create_connection_lsl_stream, daemon=True)
        self.create_connection_lsl_stream_thread.start()
        self.update_lsl_connection_state_label()

        self.main_loop()

        
    # =========================================================
    # VIDEO CAPTURE UTILITY FUNCTIONS
    # =========================================================
    def set_video_capture_properties(self, cap: cv2.VideoCapture, frame_width, frame_heigth, fps, buffersize):
        #cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y', 'U', 'Y', '2'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_heigth)
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, buffersize)
    

    def get_resolution(self, cap: cv2.VideoCapture):
        return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    

    # =========================================================
    # GUI INITIALIZATION
    # =========================================================
    def init_gui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack()

        # putting gui_row += 1 before each UI element code is enough to ensure it does not overlap with other elements
        gui_row = 0

        gui_row += 1
        ttk.Label(
            main_frame, 
            text="Record videos from two cameras upon LSL triggers", 
            font=("Helvetica", 16, "bold")
        ).grid(row=gui_row, column=0, columnspan=2, padx=10, pady=10)

        # --- Video previews ---
        gui_row += 1
        video_previews_frame = ttk.Frame(main_frame)
        video_previews_frame.grid(row=gui_row, column=0, columnspan=2, padx=10, pady=10)

        ttk.Label(
            video_previews_frame, 
            text=f"Camera {LEFT_CAMERA_ID}", 
            font=("Helvetica", 14, "bold")
        ).grid(row=gui_row, column=0, padx=10, pady=10)
        ttk.Label(
            video_previews_frame, 
            text=f"Camera {RIGHT_CAMERA_ID}", 
            font=("Helvetica", 14, "bold")
        ).grid(row=gui_row, column=1, padx=10, pady=10)

        gui_row += 1
        self.left_camera_preview_label = ttk.Label(video_previews_frame)
        self.left_camera_preview_label.grid(row=gui_row, column=0, padx=10, pady=10)
        self.right_camera_preview_label = ttk.Label(video_previews_frame)
        self.right_camera_preview_label.grid(row=gui_row, column=1, padx=10, pady=10)

        # Connected receivers
        gui_row += 1
        connession_state_frame = ttk.Frame(main_frame)
        connession_state_frame.grid(row=gui_row, column=0, columnspan=2, padx=10, pady=10)
        self.connection_state_label = ttk.Label(
            connession_state_frame, 
            text="Checking connection with commander...", 
            font=("Helvetica", 10, "bold"),
            foreground="red"
        )
        self.connection_state_label.grid(row=gui_row, column=0, columnspan=2)

        # --- Logging box ---
        gui_row += 1
        log_box_frame = ttk.Frame(main_frame)
        log_box_frame.grid(row=gui_row, column=0, columnspan=2, padx=10, pady=10)

        self.log_text = tk.Text(log_box_frame, width=150, height=10) # box
        self.log_text.grid(row=gui_row, column=0, columnspan=2, pady=5)
        
        # --- Status at the bottom of the screen ---
        gui_row += 1
        self.status_bottom_label = ttk.Label(
            root, 
            text="Status: Ready to receive START trigger", 
            background="grey", 
            foreground="white",
            anchor="center"
        )
        self.status_bottom_label.pack(side=tk.BOTTOM, fill=tk.X)


    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        print(f"[{timestamp}] {message}")
    

    # =========================================================
    # DISPLAY VIDEO PREVIEW ON GUI (Consumer)
    # =========================================================
    def update_video_previews(self):
        if self.is_reading_frames:
            frame1 = self.left_camera_reader_and_rec.get_preview_frame()
            if frame1 is not None:
                frame1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2RGB)
                frame1 = cv2.resize(frame1, (VIDEO_PREVIEW_WIDTH, VIDEO_PREVIEW_LENGTH))
                self.photo1 = ImageTk.PhotoImage(image=Image.fromarray(frame1))
                self.left_camera_preview_label.config(image=self.photo1)

            frame2 = self.right_camera_reader_and_rec.get_preview_frame()
            if frame2 is not None:
                frame2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2RGB)
                frame2 = cv2.resize(frame2, (VIDEO_PREVIEW_WIDTH, VIDEO_PREVIEW_LENGTH))
                self.photo2 = ImageTk.PhotoImage(image=Image.fromarray(frame2))
                self.right_camera_preview_label.config(image=self.photo2)

            self.root.after(VIDEO_PREVIEW_REFRESH_PERIOD_MS, self.update_video_previews)


    # =========================================================
    # Connect to Commander via LSL (Lab Streaming Layer)
    # =========================================================
    # since tkinter is not thread safe it could be dangerous to update the gui from inside the thread
    # is better to have 2 functions, one that is a thread and edit variables
    # and the other that uses that variables to update the GUI
    def _create_connection_lsl_stream(self):
        lsl_stream_name = LSL_RECORDING_TRIGGER_STREAM_NAME
        while self.search_for_commander:
            try:        
                streams = resolve_byprop('name', lsl_stream_name, timeout=LSL_WAITING_COMMANDER_TIMEOUT_SEC)
                if streams: # if some streams with that name are found, pick only the first one and exit the loop
                    self.inlet_info = streams[0]
                    self.inlet = StreamInlet(self.inlet_info)
                    self.search_for_commander = False
            except Exception as e:
                print(f"Connection attempt failed with exception: {e}")
    

    def update_lsl_connection_state_label(self):
        if self.inlet is None:
            self.root.after(LSL_CONNECTION_STATE_LABEL_REFRESH_PERIOD_MS, self.update_lsl_connection_state_label)
        else:
            self.log(f"✅ Connected to LSL stream")
            self.log(f"ℹ️  Stream info: {self.inlet_info.name()} ({self.inlet_info.type()})")
            self.connection_state_label.config(text="✅ Connected to LSL stream", foreground="green")
            

    # =========================================================
    # Listen on the inlet and follow START and STOP commands
    # =========================================================
    def main_loop(self):
        """
        listen on the inlet:
        - if START message arrives start recording and save data accordingly
        - if STOP message arrives stop recording and save both audio and merge them
        """
        if self.inlet: # if there is a connection, pull a sample from it, otherwise wait time in order to obtain inlet from create_connection lsl_stream
            sample, timestamp = self.inlet.pull_sample(timeout=0)
            if sample:
                self.log(f"📥 Received: {sample}")
                if sample[0] not in ["START", "STOP"]:
                    print("Invalid message received, this message will be ignored")

                elif sample[0] == "START":
                    if  self.is_busy:
                        # check here in order to not lose time creating a directory that will not be used
                        self.log("⚠️  Busy in recording operations, ignoring START trigger")
                    else:
                        self.is_busy = True
                        self.status_bottom_label.config(text="Status: Recording data...", background="red")

                        # ########## read the content of the message sended by the commander ##########
                        # used for output files
                        self.run_session_dir = Path(sample[1]) # output dir where to save all the data from the runs in that session
                        self.run_output_filename_prefix = sample[2] # prefix for the session output files
                        self.run_id = sample[3]
                        # used for metadata files
                        self.run_participant_id = sample[4]
                        self.run_session_id = sample[5]
                        self.run_task_long_name = sample[6]                        
                        
                        # ########## Create the output directories ##########

                        # Create the root output directory
                        try:
                            self.run_session_dir.mkdir(exist_ok=True, parents=True)
                        except Exception as e:
                            print(f"Error while creating the output path: {self.run_session_dir}\n{e}")
                            self.on_closing()
                        
                        # Inside the session dir, create the directories for storing specific kind of data

                        # Create video directory, used for storing video data
                        self.run_output_dir_video = self.run_session_dir / "video"
                        try:
                            self.run_output_dir_video.mkdir(exist_ok=True)
                        except Exception as e:
                            print(f"Error while creating the output directory: {self.run_output_dir_video}\n{e}")
                            self.on_closing()

                        # Create audio directory, used for storing audio data
                        self.run_output_dir_audio = self.run_session_dir / "audio"
                        try:
                            self.run_output_dir_audio.mkdir(exist_ok=True)
                        except Exception as e:
                            print(f"Error while creating the output directory: {self.run_output_dir_audio}\n{e}")
                            self.on_closing()

                        # ########## Determine all output file paths and save them in class variables ##########
                        self.run_temp_file_paths["left_camera_video"] = self.run_output_dir_video / LEFT_CAMERA_VIDEO_FILENAME
                        self.run_temp_file_paths["left_camera_audio"] = self.run_output_dir_video / LEFT_CAMERA_AUDIO_FILENAME
                        self.run_temp_file_paths["right_camera_video"] = self.run_output_dir_video / RIGHT_CAMERA_VIDEO_FILENAME
                        self.run_temp_file_paths["right_camera_audio"] = self.run_output_dir_video / RIGHT_CAMERA_AUDIO_FILENAME

                        self.run_output_file_paths["left_camera_merged"] = self.run_output_dir_video / get_camera_merged_output_filename(
                            self.run_output_filename_prefix, 
                            self.run_id,
                            LEFT_CAMERA_ID
                        )
                        self.run_output_file_paths["right_camera_merged"] = self.run_output_dir_video / get_camera_merged_output_filename(
                            self.run_output_filename_prefix, 
                            self.run_id,
                            RIGHT_CAMERA_ID
                        )
                        if DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC:
                            self.run_output_file_paths["dog_neck_microphone_audio"] = self.run_output_dir_audio / get_dog_microphone_output_filename(
                                self.run_output_filename_prefix,
                                self.run_id
                            )
                        if OWNER_MICROPHONE_CONNECTED_TO_THIS_PC:
                            self.run_output_file_paths["owner_microphone_audio"] = self.run_output_dir_audio / get_owner_microphone_output_filename(
                                self.run_output_filename_prefix,
                                self.run_id
                            )

                        # ########## Start recording data ##########
                        self.log(f"⏺️ Recording data in: {self.run_session_dir}")
                        self.start_recording_data()

                elif sample[0] == "STOP":
                    if not self.is_busy:
                        self.log("⚠️  No recording operation is being performed, ignoring STOP trigger")
                    if self.is_busy and not self.is_recording:
                        self.log("⚠️  Busy in post recording operations, ignoring STOP trigger")
                    elif self.is_busy and self.is_recording:
                        self.log("⏹️ Stop recording and saving data...")
                        self.stop_recording_and_save_data()
                        self.is_busy = False # false because the program has ended all recording and saving data operations
                        self.log("✅ All data saved successfully. Ready to start new recording")
                        self.status_bottom_label.config(text="Status: Ready to receive START trigger", background="grey")

        self.root.after(10, self.main_loop) # retry after 10 ms, this way the delay between the sending of the command and the execution is minimized
    
    
    # =========================================================
    # Start recording audio and video data files
    # =========================================================
    def start_recording_data(self):
        if self.is_recording:
            raise Exception("⚠️  Impossible to start recording. The app is already recording")
        
        self.is_recording = True
    
        self.ses_scans_list = None
        self.ses_scans_list = [] # list of dict used for storing the path and timestamp of first data of each file created in this run
        
        # Start left camera video recording
        acq_time = self.left_camera_reader_and_rec.start_recording(
            self.run_temp_file_paths["left_camera_video"],
            VIDEO_WIDTH,
            VIDEO_HEIGHT,
            VIDEO_FPS
        )
        # Start left camera audio recording
        self.left_camera_audio_recorder.start_recording(
            self.run_temp_file_paths["left_camera_audio"],
            AUDIO_SAMPLERATE, 
            AUDIO_CHANNELS
        )
        # since the audio and video recording start almost at the same time we can use the same acq_time for the merge data
        # particularly we use the acq_time of the video since it is the one that starts first, and so it is the one that better represents the start of the recording
        self.ses_scans_list.append({
            "file_path": self.run_output_file_paths["left_camera_merged"],
            "acq_time": acq_time
        })


        # Start right camera video recording
        acq_time = self.right_camera_reader_and_rec.start_recording(
            self.run_temp_file_paths["right_camera_video"],
            VIDEO_WIDTH,
            VIDEO_HEIGHT,
            VIDEO_FPS
        )
        # Start right camera audio recording
        self.right_camera_audio_recorder.start_recording(
            self.run_temp_file_paths["right_camera_audio"],
            AUDIO_SAMPLERATE, 
            AUDIO_CHANNELS
        )
        # since the audio and video recording start almost at the same time we can use the same acq_time for the merge data
        # particularly we use the acq_time of the video since it is the one that starts first, and so it is the one that better represents the start of the recording
        self.ses_scans_list.append({
            "file_path": self.run_output_file_paths["right_camera_merged"],
            "acq_time": acq_time
        })

        # Start dog neck microphone
        if DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC:
            acq_time = self.dog_neck_microphone_audio_recorder.start_recording(
                self.run_output_file_paths["dog_neck_microphone_audio"],
                AUDIO_SAMPLERATE, 
                AUDIO_CHANNELS
            )
            self.ses_scans_list.append({
                "file_path": self.run_output_file_paths["dog_neck_microphone_audio"],
                "acq_time": acq_time
            })

        # Start owner microphone
        if OWNER_MICROPHONE_CONNECTED_TO_THIS_PC:
            print("owner mic")
            print(datetime.now().isoformat())
            acq_time = self.owner_microphone_audio_recorder.start_recording(
                self.run_output_file_paths["owner_microphone_audio"],
                AUDIO_SAMPLERATE, 
                AUDIO_CHANNELS
            )
            self.ses_scans_list.append({
                "file_path": self.run_output_file_paths["owner_microphone_audio"],
                "acq_time": acq_time
            })


    # =========================================================
    # Stop recording audio and video data files
    # =========================================================
    def stop_recording_and_save_data(self):
        if not self.is_recording:
            raise Exception("⚠️  Impossible to stop recording. The app is not recording")
        
        self.is_recording = False
        
        threads_to_join = []

        # Stop left camera
        threads_to_join.append(self.left_camera_reader_and_rec.stop_recording())
        threads_to_join.append(self.left_camera_audio_recorder.stop_recording())
        
        # Stop rigth camera
        threads_to_join.append(self.right_camera_reader_and_rec.stop_recording())
        threads_to_join.append(self.right_camera_audio_recorder.stop_recording())

        # Stop dog neck microphone
        if DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC:
            threads_to_join.append(self.dog_neck_microphone_audio_recorder.stop_recording())
        
        # Stop owner microphone
        if OWNER_MICROPHONE_CONNECTED_TO_THIS_PC:
            threads_to_join.append(self.owner_microphone_audio_recorder.stop_recording())
        
        # wait for all processes to terminate
        for t in threads_to_join:
            if t:
                t.join()
        
        self.log("Recording stopped successfully. Please wait for all data to be saved...")
        
        # Log the saved recording paths
        if DOG_NECK_MICROPHONE_CONNECTED_TO_THIS_PC:
            self.log(f"Recording saved: {self.run_output_file_paths['dog_neck_microphone_audio']}")
        
        if OWNER_MICROPHONE_CONNECTED_TO_THIS_PC:
            self.log(f"Recording saved: {self.run_output_file_paths['owner_microphone_audio']}")
                
        self.log("⚙️ Merging cameras audio and videos...")
        
        merge_video_and_audio(
            output_file_path=self.run_output_file_paths["left_camera_merged"],
            video_file_path=self.run_temp_file_paths["left_camera_video"],
            audio_file_path=self.run_temp_file_paths["left_camera_audio"],
        )
        self.log(f"Recording saved: {self.run_output_file_paths['left_camera_merged']}")

        merge_video_and_audio(
            output_file_path=self.run_output_file_paths["right_camera_merged"],
            video_file_path=self.run_temp_file_paths["right_camera_video"],
            audio_file_path=self.run_temp_file_paths["right_camera_audio"],
        )
        self.log(f"Recording saved: {self.run_output_file_paths['right_camera_merged']}")

        if DELETE_CAMERA_AUDIO_AND_VIDEO_ONLY_FILES_AFTER_MERGE:
            for f in self.run_temp_file_paths.values():
                os.remove(f)
                # self.log(f"Removed file: {f}")
        
        # Now that all the data have been saved, write metadata about the recording
        # if WRITE_SESSIONS_METADATA_ON_PC:
        #     dataset_utils.write_on_sessions(self.run_participant_id, self.run_session_id)
        #     self.log(f"Session metadata saved: {self.run_session_dir / '..' / f'{self.run_participant_id}_sessions.tsv'}")
        
        # add to scans.tsv metadata file the acq_time of the recorded files
        dataset_utils.write_on_scans_tsv(self.run_participant_id, self.run_session_id, self.ses_scans_list)
        self.log(f"Scans metadata saved: {self.run_session_dir / 'scans.tsv'}")

    # =========================================================
    # Close application
    # =========================================================
    def on_closing(self):
        """Method for handling the shut down of the application"""
        if self.is_busy:
            if self.is_recording == False:
                # in this context the application has already received STOP signal and is finishing saving all the data
                # make the user wait
                messagebox.showwarning("Warning", "The application is finishing saving the recorded data, please wait")
                return
            else:
                # in this context the application is recording data but the stop signal has not arrived yet
                # ask the user to stop the recording or not
                user_selection_save_and_quit_application = messagebox.askyesno("Recording in progress",
                                "Recording in progress. Stop the recordings and exit? The data being currently recorded will be saved.")
                if user_selection_save_and_quit_application:
                    self.stop_recording_and_save_data()
                else:
                    # if the user refuse to exit just return and continue with normal flow
                    return            

        print("⏹️  Closing application...")
        
        self.root.destroy()

        if self.is_reading_frames:
            # this means that the program had surpassed the initialization phase with success and the camera previews were active
            self.left_camera_reader_and_rec.stop_reading()
            self.right_camera_reader_and_rec.stop_reading()

            # if the commander was found, close the stream
            # otherwise stop the thread that is searching for it
            if self.inlet:
                self.inlet.close_stream()
            else:
                self.search_for_commander = False
                if self.create_connection_lsl_stream_thread:
                    self.create_connection_lsl_stream_thread.join()

        # in every case release the video capture objects for both cameras and close the LSL stream

        if self.cap1.isOpened():
            self.cap1.release()
        if self.cap2.isOpened():
            self.cap2.release()
        
        print("✅ Application closed successfully")
        exit(0)


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    try:
        import pylsl
    except ImportError:
        print("❌ ERROR: pylsl not found")
        print("Install with: pip install pylsl")
        exit(1)
    
    root = tk.Tk()
    app = SimpleLSLRecorderApp(root)
    root.mainloop()
