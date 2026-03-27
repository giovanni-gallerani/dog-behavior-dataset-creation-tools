# for searching subject IDs and determine the ouput path for the receivers
from pathlib import Path
import csv

# for GUI
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import threading    # used for searching LSL connection while continuing to enable the user interaction with UI
import time
import os

# for LSL
from pylsl import StreamInfo, StreamOutlet

# APP CONFIGURATION
# utility functions and constant variables used for dataset creation
import dataset_utils

# names used in the GUI and error messages
PARTICIPANT_ID_GUI_NAME = f"{dataset_utils.ParticipantsColumns.PARTICIPANT_ID.long_name}"
SESSION_TYPE_GUI_NAME = "Session Type"
SESSION_ID_GUI_NAME = dataset_utils.SessionsColumns.SESSION_ID.long_name
SESSION_ID_NUMBER_GUI_NAME = f"{SESSION_ID_GUI_NAME} Number"
TASK_GUI_NAME = "Task"
RUN_INDEX_GUI_NAME = "Run Index"

SESTYPE_PRESESSION_GUI_NAME = dataset_utils.SessionTypes.PRESESSION.long_name
SESTYPE_SCENARIOS_GUI_NAME = dataset_utils.SessionTypes.SCENARIOS.long_name

TASKTYPE_FREEBEH_GUI_NAME = dataset_utils.TaskTypes.CALIBRATION.long_name
TASKTYPE_RESTING_GUI_NAME = dataset_utils.TaskTypes.RESTING.long_name
TASKTYPE_TREAT_GUI_NAME = dataset_utils.TaskTypes.TREAT.long_name
TASKTYPE_CONVERSATION_GUI_NAME = dataset_utils.TaskTypes.CONVERSATION.long_name

# --- Participants ---
TEST_PARTICIPANT_ENTRY = f"{dataset_utils.RECORDING_TEST_PARTICIPANT_ID}: only for tests. Use participant_adder.py to add others." # used when Recording Test is selected
PARTICIPANTS_LIST_REFRESH_PERIOD_MS = 100 # Refresh the participants list after this time, so that newly adde participants added will get displayed without needing to close and reopen the app

# --- Run Index ---
AUTO_RUN_INDEX_REFRESH_PERIOD_MS = 100 # Refresh the index number after this time

# --- LSL connections ---
WAITING_FOR_RECEIVERS_TIMEOUT_SEC = 1   # Max time waiting for a receiver response
QUERYING_FOR_RECEIVERS_REFRESH_PERIOD_SEC = 1 # Time that must pass before trying again to get a response from a receiver
RECEIVERS_LABEL_REFRESH_PERIOD_MS = (WAITING_FOR_RECEIVERS_TIMEOUT_SEC + QUERYING_FOR_RECEIVERS_REFRESH_PERIOD_SEC) * 1000 # Refresh period for label that indicate the presence of connection with receivers


class LSLCommanderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LSL Recording Commander")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        # State of the app
        self.is_recording = False
        # Receiver monitoring variables
        self.monitor_receivers = True # flag used for managing the thread that monitor if any consumers are connected
        self.is_connected_to_receivers = False
        # Time Counter variables
        self.time_counter_hours = 0
        self.time_counter_minutes = 0
        self.time_counter_seconds = 0
        # Create LSL outlet for sending triggers
        print("Creating LSL outlet...")
        info = StreamInfo(
            name="RecordingTrigger",
            type="Markers",
            channel_count=7,
            nominal_srate=0,
            channel_format="string",
            source_id="recording_trigger_001"
        )
        self.outlet = StreamOutlet(info)
        print("✅ LSL outlet created: RecordingTrigger")
        print("   Broadcasting to network...")
        # GUI
        self.init_gui()
        # Once initialized the GUI, start the processes that periodically refresh it
        self.refresh_participants_combobox() # check periodically for changes in the participants file and update combobox accordingly
        self.refresh_run_index() # check periodically if the fields for calculating it are ready, if they are determine run index
        self.monitor_receivers_thread = threading.Thread(target=self._monitor_receivers, daemon=True)
        self.monitor_receivers_thread.start()
        self.root.after(RECEIVERS_LABEL_REFRESH_PERIOD_MS, self.update_receivers_connection_state_label)


    # ########## GUI ##########
    def init_gui(self):
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack()
        
        # putting gui_row += 1 before each UI element code is enough to ensure it does not overlap with other elements
        gui_row = 0

        gui_row += 1
        ttk.Label(
            main_frame, 
            text="Record data on the receivers by sending LSL trigger", 
            font=("Helvetica", 16, "bold")
        ).grid(row=gui_row, column=0, columnspan=2, padx=10, pady=10)
        
        # --- Create a Frame to hold the entries, these are used to determine the path into which save the data on the receivers ---
        gui_row += 1
        form_frame = ttk.Frame(main_frame)
        form_frame.grid(row=gui_row, column=0, padx=10, pady=10)

        labels_column = 0 # the column for the labels
        entry_labels_padx = 5 # padding for the labels
        entries_column = 1 # the column for the entry widgets
        entries_width = 50 # width for the entry widgets
        form_rows_pady = 5 # padding between entry rows

        # participant id
        gui_row += 1
        ttk.Label(form_frame, text=f"{PARTICIPANT_ID_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=entry_labels_padx)
        self.participant_stringvar = tk.StringVar()
        self.participant_combobox = ttk.Combobox(
            form_frame, 
            textvariable=self.participant_stringvar, 
            values=dataset_utils.list_participants_summary(), 
            state="readonly", 
            width=entries_width
        )
        self.participant_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")
        self.participant_combobox.bind("<<ComboboxSelected>>", self.on_participant_change)

        # session type
        gui_row += 1
        tk.Label(form_frame, text=f"{SESSION_TYPE_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=entry_labels_padx)
        self.session_type_long_name_stringvar = tk.StringVar()
        self.session_type_combobox = ttk.Combobox(
            form_frame, 
            textvariable=self.session_type_long_name_stringvar, 
            values=dataset_utils.SessionTypes.list_long_names(), 
            state="readonly", 
            width=entries_width
        )
        self.session_type_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")
        self.session_type_combobox.bind("<<ComboboxSelected>>", self.on_session_type_change)

        # session id num
        gui_row += 1
        self.session_id_num_stringvar = tk.StringVar()
        ttk.Label(form_frame, text=f"{SESSION_ID_NUMBER_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=entry_labels_padx)
        self.session_id_num_entry = tk.Entry(form_frame, width=entries_width, textvariable=self.session_id_num_stringvar, state="disabled")
        self.session_id_num_entry.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        # toggle for automatically calculating session_id
        gui_row += 1
        self.auto_calculate_session_id_num_booleanvar = tk.BooleanVar(value=True)
        self.auto_calculate_session_id_num_checkbutton = ttk.Checkbutton(
            form_frame, 
            text=f"Auto Calculate {SESSION_ID_NUMBER_GUI_NAME}", 
            variable=self.auto_calculate_session_id_num_booleanvar, 
            command=self.on_auto_calculate_session_id_num_toggle
        )
        self.auto_calculate_session_id_num_checkbutton.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        # task
        gui_row += 1
        tk.Label(form_frame, text=f"{TASK_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=entry_labels_padx)
        self.task_long_name_stringvar = tk.StringVar() # default value is ""
        self.task_combobox = ttk.Combobox(
            form_frame, 
            textvariable=self.task_long_name_stringvar, 
            values=[], # available tasks depend on the session type selected, starts empty, once the user select a session type it gets populated
            state = "disabled", # disabled by default, once a session type get selected it activates
            width=entries_width
        )
        self.task_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")
        
        # run index
        gui_row += 1
        self.run_index_stringvar = tk.StringVar()
        # The reason StringVar is used instead of IntVar is to have the box empty when there is no way to calculate its value.
        # Using IntVar would cause the entry default value to be 0 instead, and that could be confusing for the user.
        ttk.Label(form_frame, text=f"{RUN_INDEX_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=entry_labels_padx)
        self.run_index_entry = tk.Entry(form_frame, width=entries_width, textvariable=self.run_index_stringvar, state="disabled")
        self.run_index_entry.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        # toggle for automatically calculating run index
        gui_row += 1
        self.auto_calculate_run_index_booleanvar = tk.BooleanVar(value=True)
        self.auto_calculate_run_index_checkbutton = ttk.Checkbutton(
            form_frame, 
            text=f"Auto Calculate {RUN_INDEX_GUI_NAME}", 
            variable=self.auto_calculate_run_index_booleanvar, 
            command=self.on_auto_calculate_run_index_toggle
        )
        self.auto_calculate_run_index_checkbutton.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        # --- Create a Frame to hold connected receivers, time counter and start and stop buttons ---
        gui_row += 1
        recording_commands_frame = ttk.Frame(main_frame)
        recording_commands_frame.grid(row=gui_row, column=0, padx=10, pady=10)

        # Time Counter
        gui_row += 1
        self.time_counter_label = tk.Label(recording_commands_frame, text=self.get_time_counter_text(), font=("Helvetica", 25, "bold"), fg="grey")
        self.time_counter_label.grid(row=gui_row, column=0, columnspan=2, pady=10)

        # Connected receivers
        gui_row += 1
        self.receiver_count_label = tk.Label(recording_commands_frame, text="Checking connections with recorders......", font=("Helvetica", 10, "bold"), fg="orange")
        self.receiver_count_label.grid(row=gui_row, column=0, columnspan=2, pady=10)
        
        # Start and Stop recording buttons
        start_stop_buttons_width = 15
        start_stop_buttons_height = 2

        gui_row += 1
        self.start_btn = tk.Button(
            recording_commands_frame, 
            text="⏺ REC", 
            font=("Helvetica", 12, "bold"),
            bg="white", 
            fg="red",
            command=self.send_start_trigger,
            width=start_stop_buttons_width,
            height=start_stop_buttons_height
        )
        self.start_btn.grid(row=gui_row, column=0, padx=5, pady=10)

        self.stop_btn = tk.Button(
            recording_commands_frame, 
            text="⏹ STOP", 
            font=("Helvetica", 12, "bold"),
            bg="white", 
            fg="black",
            command=self.send_stop_trigger,
            width=start_stop_buttons_width,
            height=start_stop_buttons_height,
            state="disabled"
        )
        self.stop_btn.grid(row=gui_row, column=1, padx=5, pady=10)

        # --- Create a Frame to hold the logging box ---
        gui_row += 1
        log_box_frame = ttk.Frame(main_frame)
        log_box_frame.grid(row=gui_row, column=0, padx=10, pady=10)

        # Logging box
        gui_row += 1
        self.log_text = tk.Text(log_box_frame, width=185, height=25) # box put 80 10 for screenshot purposes
        self.log_text.grid(row=gui_row, column=0, columnspan=2, pady=5)
        self.log("System ready")
        self.log("📡 Broadcasting on network")
        
        # --- Status at the bottom of the screen ---
        gui_row += 1
        self.status_bottom_label = tk.Label(
            root, 
            text="Status: Ready to send triggers", 
            bg="grey", 
            fg="white",
            font=("Helvetica", 10)
        )
        self.status_bottom_label.pack(side=tk.BOTTOM, fill=tk.X)
    

    # ########## PARTICIPANTS LIST FUNCTIONS ##########
    def refresh_participants_combobox(self):
        """
        Utility function to refresh the subjects list in the combobox.
        Calls itself periodically while not recording (for efficiency).
        """
        if self.is_recording == False:
            available_participants_list = dataset_utils.list_participants_summary()

            # refresh the list of available subject, so that if there are changes to participants.tsv file they will be displayed
            self.participant_combobox["values"] = None
            self.participant_combobox["values"] = [TEST_PARTICIPANT_ENTRY] + available_participants_list
            
            selected_participant = self.participant_stringvar.get()
            if selected_participant != TEST_PARTICIPANT_ENTRY and selected_participant not in available_participants_list:
                # this happens when a participant has been deleted or changed in a way that would affect the preview while the program was running
                self.participant_stringvar.set("") # removes the previous subject from the box
        self.root.after(PARTICIPANTS_LIST_REFRESH_PERIOD_MS, self.refresh_participants_combobox)


    # ########## FUNCTIONS USED FOR UPDATING SESSION ID NUMBER SELECTION IN THE GUI ##########
    def refresh_session_id_num(self):
        """utility function that updates the value of session id with the highest one not used"""
        # check if subject and session type have been selected, without their values is not possible to calculate the session_id number
        participant_summary_selected = self.participant_stringvar.get() # in the format "sub-XX: description"
        participant_id = participant_summary_selected.split(":")[0] # take only the participant_id part (e.g. "sub-01")
        session_type_long_name = self.session_type_long_name_stringvar.get()
        if participant_summary_selected == "" or session_type_long_name == "":   
            self.session_id_num_stringvar.set("") # if some of the values necessary to determine the next session ID is missing keep it to ""
        else:
            next_session_id_num = dataset_utils.calculate_next_session_id_num(participant_id, session_type_long_name)
            self.session_id_num_stringvar.set(next_session_id_num)       
    
    def refresh_run_index(self):
        """
        Utility function that updates the preview on the GUI about the run index that.
        Calls itself periodically while not recording and if the option is active (for efficiency).
        """
        if self.auto_calculate_run_index_booleanvar.get() and not self.is_recording:
            # extract values from the GUI, see if they are valid for calculating run
            # participant_id
            participant_summary_selected = self.participant_stringvar.get() # in the format "sub-XX: description"
            participant_id = participant_summary_selected.split(":")[0] # take only the participant_id part (e.g. "sub-01")
            session_type_long_name = self.session_type_long_name_stringvar.get()
            try:
                session_id_num = int(self.session_id_num_stringvar.get())
            except ValueError:
                session_id_num = 0 # session id num cannot be 0, this 0 is used to make the following if fail
            task_long_name = self.task_long_name_stringvar.get()
            
            # all four fields are necessary to calculate the run index are present, try to calculate it
            if participant_summary_selected != "" and session_type_long_name != "" and session_id_num > 0 and task_long_name != "":
                next_run_index = dataset_utils.calculate_next_run_index(participant_id, session_type_long_name, session_id_num, task_long_name)
                self.run_index_stringvar.set(next_run_index)
            else:
                self.run_index_stringvar.set("")
        
        self.root.after(AUTO_RUN_INDEX_REFRESH_PERIOD_MS, self. refresh_run_index)
    

    def on_auto_calculate_session_id_num_toggle(self):
        """this function is used for activating/disabling the entry. When the entry is activated, the session id number gets calculated"""
        if self.auto_calculate_session_id_num_booleanvar.get() == True:
            self.session_id_num_entry.config(state="disabled")
            self.refresh_session_id_num()
        else:
            self.session_id_num_entry.config(state="normal")
    

    def on_participant_change(self, event):
        """
        Utility function that is called every time the partcipant id is changed by the user.
        if the checkbox for automatically calculting session id num is active, update session id number.
        This is done since session number depends on the participant. A participant could be at its 3rd session, and one at its 1st.
        """
        if self.auto_calculate_session_id_num_booleanvar.get():
            self.refresh_session_id_num()


    def on_session_type_change(self, event):
        """
        Utility function that is called every time the session type is changed by the user.
        Changes the list of available tasks and participants based of the session.
        When changing to test recording session participant combobox gets deactivated nad sub-00 get setted.
        When changing from a test recording to a normal session the participant sub-00 gets removed. And the participant combobox gets activated again.
        refresh_participant_combobox then will create a list of possible participants.
        Also, if the checkbox for automatically calculting session id num is active, updates session id number based on participant and session type.
        """     
        session_type = self.session_type_long_name_stringvar.get()
        if session_type == SESTYPE_PRESESSION_GUI_NAME:
            self.task_combobox.config(state="disabled")
            self.task_long_name_stringvar.set(TASKTYPE_FREEBEH_GUI_NAME)
        elif session_type == SESTYPE_SCENARIOS_GUI_NAME:
            self.task_combobox.config(state="readonly", values=[TASKTYPE_CONVERSATION_GUI_NAME, TASKTYPE_TREAT_GUI_NAME, TASKTYPE_RESTING_GUI_NAME])
            self.task_long_name_stringvar.set("") # reset the field, so that the user can select one of the options
        else:
            self.task_combobox.config(state="disabled")
            self.task_long_name_stringvar.set("")
            self.log("No tasks available for this session at the moment")
        
        # in the end, if auto flag is active, refresh the session id according to the selected session type
        if self.auto_calculate_session_id_num_booleanvar.get():
            self.refresh_session_id_num()
        

    def on_auto_calculate_run_index_toggle(self):
        """this function is only used for activating/disabling the entry for run index, the value iniside it is changed periodically by refresh_run_index"""
        if self.auto_calculate_run_index_booleanvar.get():
            self.run_index_entry.config(state="disabled")
        else:
            self.run_index_entry.config(state="normal")
    

    # ########## RECEIVERS CONNECTED LABEL FUNCTIONS ##########
    # since tkinter is not thread safe it could be dangerous to update the gui from inside the thread
    # is better to have 2 functions, one that is a thread and edit a variable
    # and the other that uses that variable to update the GUI
    def _monitor_receivers(self):
        """Monitor if receivers are connected"""
        while self.monitor_receivers:
            self.is_connected_to_receivers = self.outlet.wait_for_consumers(WAITING_FOR_RECEIVERS_TIMEOUT_SEC)
            time.sleep(QUERYING_FOR_RECEIVERS_REFRESH_PERIOD_SEC)

        
    def update_receivers_connection_state_label(self):
        "Periodically update the receivers label accordingly to state variable"
        if self.is_connected_to_receivers:
            self.receiver_count_label.config(text="✅ Receiver(s) connected", fg="green")
        else:
            self.receiver_count_label.config(text="⚠️ No receivers", fg="red")
        self.root.after(RECEIVERS_LABEL_REFRESH_PERIOD_MS, self.update_receivers_connection_state_label)
    

    # ########## LOG FUNCTION ##########
    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        print(f"[{timestamp}] {message}")

    
    # ########## TIME COUNTER FUNCTIONS ##########
    def get_time_counter_text(self) -> str:
        return f"{str(self.time_counter_hours).zfill(2)}:{str(self.time_counter_minutes).zfill(2)}:{str(self.time_counter_seconds).zfill(2)}"
    

    def start_time_counter(self):
        self.time_counter_hours = 0
        self.time_counter_minutes = 0
        self.time_counter_seconds = 0
        # turn the color to black to simbolize that the time counter is active
        self.time_counter_label.config(fg="black")
        # wait 1 second before the first update
        self.root.after(1000, self.update_time_counter)


    def update_time_counter(self):
        if self.is_recording == False:
            return
        
        self.time_counter_seconds += 1
        if self.time_counter_seconds >= 60:
            self.time_counter_seconds = 0
            self.time_counter_minutes += 1
        if self.time_counter_minutes >= 60:
            self.time_counter_minutes = 0
            self.time_counter_hours += 1
        self.time_counter_label.config(text=self.get_time_counter_text())
        # update the time counter every second
        self.root.after(1000, self.update_time_counter)


    def stop_time_counter(self):
        self.log(f"Recording length: {self.get_time_counter_text()}")
        self.time_counter_hours = 0
        self.time_counter_minutes = 0
        self.time_counter_seconds = 0
        self.time_counter_label.config(text=self.get_time_counter_text())
        # turn the color to grey to simbolize that the time counter is not active anymore
        self.time_counter_label.config(fg="grey")

    
    # ########## UTILITY FUNCTIONS FOR DISABLE ENTRY STATE DURING RECORDING AND REACTIVATING AFTER ##########
    def reactivate_entry_fields(self):
        """utility function used to reactivate entry fields after recording"""
        self.participant_combobox.config(state="readonly")
        self.session_type_combobox.config(state="readonly")
        # reactivate session id number entry only if the auto toggle is off, since if the auto toggle is on it must remain disabled
        if not self.auto_calculate_session_id_num_booleanvar.get():
            self.session_id_num_entry.config(state="normal")
        self.auto_calculate_session_id_num_checkbutton.config(state="normal")
        # when reactivating the fields activate the session type selection only for scenario, since is the only one with more than 1 option
        # giving the user the possibility to select the drop down menu and having only 1 option would be confusing
        if self.session_type_long_name_stringvar.get() == SESTYPE_SCENARIOS_GUI_NAME:
            self.task_combobox.config(state="readonly")
        if not self.auto_calculate_run_index_booleanvar.get():
            self.run_index_entry.config(state="normal")
        self.auto_calculate_run_index_checkbutton.config(state="normal")
    
    def disable_entry_fields(self):
        """utility function used to disable entry fields during recording"""
        self.participant_combobox.config(state="disabled")
        self.session_type_combobox.config(state="disabled")
        # reactivate session id number entry only if the auto toggle is off, since if the auto toggle is on it must remain disabled
        self.session_id_num_entry.config(state="disabled")
        self.auto_calculate_session_id_num_checkbutton.config(state="disabled")
        self.task_combobox.config(state="disabled")
        self.run_index_entry.config(state="disabled")
        self.auto_calculate_run_index_checkbutton.config(state="disabled")


    # ########## START AND STOP TRIGGER FUNCTIONS ##########
    def send_start_trigger(self):
        """Send the start trigger to all receivers after checking all the required fields"""

        self.start_btn.config(state="disabled")
        self.disable_entry_fields()
        
        # obtain the data inserted by the user and use it to obtain the directory path in wich the data must be saved
        participant = self.participant_stringvar.get() # in the format "sub-XX: description"
        participant_id = participant.split(":")[0] # take only the participant_id part (e.g. "sub-01")
        session_type_long_name = self.session_type_long_name_stringvar.get()
        session_id_num = self.session_id_num_entry.get()
        task_long_name = self.task_long_name_stringvar.get()
        run_index = self.run_index_stringvar.get()

        # Input validation
        missing_items_error_messages = []
        invalid_items_error_messages = []
        error_messages = []

        # if no subject was selected
        if participant == "":
            missing_items_error_messages.append(PARTICIPANT_ID_GUI_NAME)
        else:
            # if session type is not a recording test participant, check if it exist in participants.txt
            if participant != TEST_PARTICIPANT_ENTRY and participant not in dataset_utils.list_participants_summary():
                invalid_items_error_messages.append(f"Participant '{participant.split(',')[0]}' does not exist. Please select again.")
        if session_type_long_name == "":
            missing_items_error_messages.append(SESSION_TYPE_GUI_NAME)
        if session_id_num == "":
            missing_items_error_messages.append(SESSION_ID_NUMBER_GUI_NAME)
        else:
            # verify if the value of session id number is valid. if a session dir is already in use, it is still valid since there is the concept of runs
            try:
                session_id_num_int = int(session_id_num)
                if session_id_num_int < 1:
                    invalid_items_error_messages.append(f"{SESSION_ID_NUMBER_GUI_NAME}: must be a positive integer.")
            except ValueError:
                invalid_items_error_messages.append(f"{SESSION_ID_NUMBER_GUI_NAME}: must be a positive integer.")

        if task_long_name == "":
            missing_items_error_messages.append(TASK_GUI_NAME)
        if run_index == "":
            missing_items_error_messages.append(RUN_INDEX_GUI_NAME)
        else:
            # verify if the value of run index is valid.
            try:
                run_index_int = int(run_index)
                if run_index_int < 1:
                    invalid_items_error_messages.append(f"{RUN_INDEX_GUI_NAME}: must be a positive integer.")
                else:
                    if dataset_utils.run_already_exists(participant_id, session_type_long_name, session_id_num_int, task_long_name, run_index_int):
                        invalid_items_error_messages.append(f"{RUN_INDEX_GUI_NAME}: files related to this run already exist, select a different run index.")
            except ValueError:
                invalid_items_error_messages.append(f"{RUN_INDEX_GUI_NAME}: must be a positive integer.")
            # then check if it exists already in the session dir
            

        if missing_items_error_messages:
            error_messages.append("Please fill the following fields:\n" + "\n".join(missing_items_error_messages))
        if invalid_items_error_messages:
            error_messages.append("Invalid entries:\n" + "\n".join(invalid_items_error_messages))
        if error_messages:
            messagebox.showerror("Input Error", "\n\n".join(error_messages))
            # after a failed start action restore the start button to normal state and reactivate the entry fields
            self.start_btn.config(state="normal")
            self.reactivate_entry_fields()
            return
        
        # All inputs are valid, check if any receivers are connected, if not warn the user
        receivers_connected = self.outlet.wait_for_consumers(0)
        if receivers_connected == False:
            result = messagebox.askyesno(
                "No Receivers Connected",
                "⚠️  No receivers are connected!\n\n"
                "Make sure receiver programs are running.\n\n"
                "Send START trigger anyway?",
                icon="warning"
            )
            if result == False:
                # if the user cancel the action restore the start button to normal state and reactivate the entry fields
                self.start_btn.config(state="normal")
                self.reactivate_entry_fields()
                return

        # Calculate the output directory path where the receivers will save the recorded data, save it as a string since it will be sensed via LSL
        try:
            session_dir = str(dataset_utils.get_session_dir(participant_id, session_type_long_name, session_id_num_int))
            print(f"Calculated output_dir: {session_dir}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not calculate output_dir:\n{e}")
            # after a failed start action restore the start button to normal state and reactivate the entry fields
            self.start_btn.config(state="normal")
            self.reactivate_entry_fields()
            return
        
        # Calculate the output filename prefix
        try:
            output_filename_prefix = dataset_utils.get_output_filename_prefix(participant_id, session_type_long_name, session_id_num_int, task_long_name)
            print(f"Calculated output_filename_prefix: {output_filename_prefix}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not calculate output_filename_prefix:\n{e}")
            # after a failed start action restore the start button to normal state and reactivate the entry fields
            self.start_btn.config(state="normal")
            self.reactivate_entry_fields()
            return
        
        # no need to do try catch here since this 2 values have been calculated inside the previous functions, if we are here for sure they will not fail
        participant_dir = dataset_utils.get_participant_dir(participant_id)
        session_id = dataset_utils.get_session_id(session_type_long_name, session_id_num_int)
        run_id = dataset_utils.get_run_id(run_index_int)
        
        # Send START trigger
        trigger = [
            "START",
            # used for output files
            session_dir, # path where the data must be saved by the receivers
            output_filename_prefix, # prefix for all files produced by the different recording softwares
            run_id, # used at the end of the output filenames, just before the final suffix
            # used for metadata, they could be inferred from the previous 3, but it is more conveninet if they are already provided
            participant_id, # sub-<label>, used for determining the name of _sessions.tsv and _scans.tsv file
            session_id, # ses-<label>, used for determining the name of _scans.tsv and for writing _sessions.tsv
            task_long_name, # used for output files metadata
        ]
        self.outlet.push_sample(trigger)
        self.log(f"📤 Sent START trigger: {trigger}")
        if receivers_connected:
            self.log("   → Receiver(s) notified")
        else:
            self.log("   → Could not find receivers to notify")

        # Change the state to recording
        self.is_recording = True

        # Start the time counter
        self.start_time_counter()
        self.status_bottom_label.config(text=f"Status: Recording on the receivers...", bg="red")

        # when the order of sending the start trigger is issued the recording can be stopped
        self.stop_btn.config(state="normal")
        
        
    def send_stop_trigger(self):
        self.stop_btn.config(state="disabled")
        
        # Send STOP trigger
        receivers_connected = self.outlet.wait_for_consumers(0)
        trigger = [
            "STOP",
            "",
            "",
            "",
            "",
            "",
            ""
        ]
        self.outlet.push_sample(trigger)
        self.log("⏹️  Sent STOP trigger")
        if receivers_connected:
            self.log("   → Receiver(s) notified")
        else:
            self.log("   → Could not find receivers to notify")
        # Change the state to not recording
        self.is_recording = False
        # Stop the time counter
        self.stop_time_counter()
        # Signal ready state to the user
        self.status_bottom_label.config(text="Status: Ready to send triggers", bg="grey")
        self.start_btn.config(state="normal")
        self.reactivate_entry_fields()
    
    # ########## CLOSE PROGRAM FUNCTION ##########
    def on_closing(self):
        if self.is_recording:
            closing_app_answer = messagebox.askyesno("Recording in progress", "Recording in progress. Close the application? The recording will not stop.", icon="warning")
            if not closing_app_answer:
                return
        self.root.destroy()
        self.monitor_receivers = False
        if self.monitor_receivers_thread:
            self.monitor_receivers_thread.join()
        del self.outlet
        print("Application closed successfully")


if __name__ == "__main__":
    # Check if pylsl is installed
    try:
        import pylsl
        print("✅ pylsl found")
    except ImportError:
        print("❌ ERROR: pylsl not installed")
        print("Install with: pip install pylsl")
        exit(1)
    
    root = tk.Tk()
    app = LSLCommanderApp(root)
    root.mainloop()