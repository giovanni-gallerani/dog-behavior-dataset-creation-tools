# for GUI
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

# for fuzzy string matching
import unicodedata
from rapidfuzz import fuzz
import operator

# for saving subject files
from pathlib import Path
import csv
import os

# utility functions and constant variables used for dataset creation
import dataset_utils

# output file
DATASET_ROOT = dataset_utils.SOURCE_DATASET_ROOT
OUTPUT_FILE_PATH = dataset_utils.PARTICIPANTS_FILE_PATH
PARTICIPANTS_SPECIES_LONG_NAME = dataset_utils.SpeciesLevels.DOG.long_name

# names used in the GUI and error messages
PARTICIPANT_ID_NUMBER_GUI_NAME = f"{dataset_utils.ParticipantsColumns.PARTICIPANT_ID.long_name} Number"
BREED_GUI_NAME = dataset_utils.ParticipantsColumns.BREED.long_name
SEX_GUI_NAME = dataset_utils.ParticipantsColumns.SEX.long_name
NEUTERED_GUI_NAME = dataset_utils.ParticipantsColumns.NEUTERED.long_name
AGE_YEARS_FIELD_GUI_NAME = "Age (years field)"
AGE_MONTHS_FIELD_GUI_NAME = "Age (months field)"
WEIGHT_KG_GUI_NAME = dataset_utils.ParticipantsColumns.WEIGHT_KG.long_name
DAILY_TIME_WITH_OWNER_H_GUI_NAME = dataset_utils.ParticipantsColumns.DAILY_TIME_WITH_OWNER_H.long_name
PROVENANCE_GUI_NAME = dataset_utils.ParticipantsColumns.PROVENANCE.long_name

# GUI configuration
LISTBOX_BREED_HEIGHT = 9 # number of visible items in the breed listbox
TRESHOLD_PERCENTAGE_FUZZY_SCORE = 60 # minimum score for fuzzy matching to make a breed appear in the listbox while typing
AUTO_PARTICIPANT_ID_NUM_REFRESH_PERIOD_MS = 100 # ms to wait before updating the value of the next participant_id the UI when auto option is active

class SubjectAdderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Dog Participant Adder")
        # Set the protocol for handling window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.init_gui()
        # Once initialized the GUI, start the processes that periodically refresh it
        self.refresh_participant_id_num()


    def on_closing(self):
        self.root.destroy()


    def init_gui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack()

        # putting gui_row += 1 before each UI element code is enough to ensure it does not overlap with other elements
        gui_row = 0

        gui_row += 1
        ttk.Label(main_frame, text="Add a new participant", font=("Helvetica", 16, "bold")).grid(row=gui_row, column=0, columnspan=2, pady=10)
        
        gui_row += 1
        ttk.Label(main_frame, text=f"The participant will be added to: {OUTPUT_FILE_PATH}").grid(row=gui_row, column=0, columnspan=2, padx=10, pady=10)

        # Create a Frame to hold the entries form
        gui_row += 1
        form_frame = ttk.Frame(main_frame)
        form_frame.grid(row=gui_row, column=0, padx=10, pady=10)

        labels_column = 0 # the column for the labels
        entries_column = 1 # the column for the value entered by the user
        entries_width = 40 # width for the entry widgets
        form_rows_pady = 5 # vertical padding between rows in the form

        gui_row += 1
        self.participant_id_num_stringvar = tk.StringVar()
        ttk.Label(form_frame, text=f"{PARTICIPANT_ID_NUMBER_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.participant_id_num_entry = tk.Entry(form_frame, width=entries_width, textvariable=self.participant_id_num_stringvar, state="disabled")
        self.participant_id_num_entry.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        self.auto_calculate_participant_id_num_booleanvar = tk.BooleanVar(value=True)
        auto_calculate_participant_id_num_checkbutton = ttk.Checkbutton(
            form_frame, 
            text=f"Auto Calculate {PARTICIPANT_ID_NUMBER_GUI_NAME}", 
            variable=self.auto_calculate_participant_id_num_booleanvar, 
            command=self.on_auto_calculate_participant_id_num_toggle
        )
        auto_calculate_participant_id_num_checkbutton.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        ttk.Label(form_frame, text=f"{BREED_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.breed_entry = ttk.Entry(form_frame, width=entries_width)
        self.breed_entry.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")
        
        # --- Create scrollbar and listbox for breed selection under the breed entry ---
        gui_row += 1
        self.breed_scrollbar = ttk.Scrollbar(form_frame, orient="vertical")
        self.breed_scrollbar.grid(row=gui_row, column=entries_column, sticky="nse")
        self.breed_listbox = tk.Listbox(form_frame, yscrollcommand=self.breed_scrollbar.set, height=LISTBOX_BREED_HEIGHT, width=entries_width-2)
        self.breed_listbox.grid(row=gui_row, column=entries_column, padx=(4, 0), sticky="w") # padx here is 4 to make it look aligned with the entry above

        # Link the scrollbar to the listbox
        self.breed_scrollbar.config(command=self.breed_listbox.yview)

        # Each time the user types in the breed entry, update the listbox
        self.breed_entry.bind("<KeyRelease>", self.update_list)

        # When the user clicks an item in the list the value is inserted into the breed entry
        self.breed_listbox.bind("<<ListboxSelect>>", self.on_list_select)

        # Initialize breed list and make it appear on the listbox
        self.breeds_list = dataset_utils.get_all_dogs_breeds_list()
        self.update_list()
        
        gui_row += 1
        ttk.Label(form_frame, text=f"{SEX_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.sex_long_name_stringvar = tk.StringVar()
        self.sex_combobox = ttk.Combobox(form_frame, textvariable=self.sex_long_name_stringvar, values=dataset_utils.SexLevels.list_long_names(), state="readonly", width=entries_width-2)
        self.sex_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        self.neutered_booleanvar = tk.BooleanVar()
        ttk.Checkbutton(form_frame, text=f"{NEUTERED_GUI_NAME}:", variable=self.neutered_booleanvar).grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")
        
        gui_row += 1
        ttk.Label(form_frame, text=f"{AGE_YEARS_FIELD_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.age_years_stringvar = tk.StringVar()
        self.age_years_combobox = ttk.Combobox(form_frame, textvariable=self.age_years_stringvar, values=list(range(31)), state="readonly", width=entries_width-2)
        self.age_years_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        ttk.Label(form_frame, text=f"{AGE_MONTHS_FIELD_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.age_months_stringvar = tk.StringVar()
        self.age_months_combobox = ttk.Combobox(form_frame, textvariable=self.age_months_stringvar, values=list(range(12)), state="readonly", width=entries_width-2)
        self.age_months_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        ttk.Label(form_frame, text=f"{WEIGHT_KG_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.weight_entry = ttk.Entry(form_frame, width=entries_width)
        self.weight_entry.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        ttk.Label(form_frame, text=f"{DAILY_TIME_WITH_OWNER_H_GUI_NAME}:").grid(
            row=gui_row, 
            column=labels_column, 
            sticky="e", 
            padx=5, 
            pady=form_rows_pady
        )
        self.hours_with_owner_daily_stringvar = tk.StringVar()
        self.hours_with_owner_daily_combobox = ttk.Combobox(
            form_frame, 
            textvariable=self.hours_with_owner_daily_stringvar, 
            values=list(range(1, 25)), # 24 hours in a day
            state="readonly", 
            width=entries_width-2 # -2 because combobox is a little larger due to the scrollbar
        )
        self.hours_with_owner_daily_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        gui_row += 1
        ttk.Label(form_frame, text=f"{PROVENANCE_GUI_NAME}:").grid(row=gui_row, column=labels_column, sticky="e", padx=5, pady=form_rows_pady)
        self.provenance_long_name_stringvar = tk.StringVar()
        self.provenance_combobox = ttk.Combobox(
            form_frame, 
            textvariable=self.provenance_long_name_stringvar, 
            values=dataset_utils.ProvenanceLevels.list_long_names(), 
            state="readonly", 
            width=entries_width-2
        )
        self.provenance_combobox.grid(row=gui_row, column=entries_column, padx=(5,0), pady=form_rows_pady, sticky="w")

        # Button to add subject
        gui_row += 1
        self.add_button = tk.Button(
            main_frame,
            text="Add Subject", 
            font=("Helvetica", 12, "bold"),
            background="white", 
            foreground="green",
            width=12,
            height=2,
            command=self.add_participant
        )
        self.add_button.grid(pady=20)


    # ########## FUNCTIONS USED FOR PARTICIPANT ID NUMBER SELECTION IN THE GUI ##########
    def refresh_participant_id_num(self):
        """
        Utility function that updates the preview on the GUI about the ID of the participant that is going to be added.
        it calls itself periodically.
        """
        if self.auto_calculate_participant_id_num_booleanvar.get(): # if the id is automatically calculated, update the value on the GUI
            next_participant_id_num = dataset_utils.calculate_next_participant_id_num()
            self.participant_id_num_stringvar.set(next_participant_id_num)
        self.root.after(AUTO_PARTICIPANT_ID_NUM_REFRESH_PERIOD_MS, self.refresh_participant_id_num)
    

    def on_auto_calculate_participant_id_num_toggle(self):
        """this function is only used for activating/disabling the entry, the value iniside it is changed periodically by refresh_participant_id_num"""
        if self.auto_calculate_participant_id_num_booleanvar.get():
            self.participant_id_num_entry.config(state="disabled")
        else:
            self.participant_id_num_entry.config(state="normal")

    # ########## FUNCTIONS USED FOR INTERACTIVE BREED SEARCH ##########
    def to_plain_ascii(self, text):
        # Normalize unicode characters to their base forms (NFD) 
        # and strip out non-ASCII characters
        return unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")


    def update_list(self, event=None):
        typed_text_lowercase = self.breed_entry.get().lower()
        ascii_typed_text_lowercase = self.to_plain_ascii(typed_text_lowercase) # used for managing foreign characters

        self.breed_listbox.delete(0, "end")

        if not typed_text_lowercase:
            filtered_list = self.breeds_list
        else:
            # In order to order the results associate to every breed a tuple: (start_score, ratio_score, ascii_breed_lowercase)
            # this is a tiered sorting logic
            # start_score is more valuable than ratio_score, that is more valuable than the alfabethical order
            # start_score is:
            # - 0 if the beginning of the string matches perfectly
            # - 1 if the beginning of the string matches perfectly, but only using plain ascii
            # - 2 otherwise
            # ratio_score is:
            # - 0 if start_score is 0 or 1
            # - otherwise is calculated using a partial ratio algorithm (better than edit distance), useful in case of typos or foreign characters

            # This way if typed_text exactly match the beginning of the breed the breeds that match it are sorted in alphabetical order
            # If that does not happen the breeds are sorted using 2 levels of priority:
            # - first the ones that matches the sitring but only in ascci (e.g. Lai and Lài)
            # - then the ones that have a fuzzy.Wratio > 60 (ratio_score < 40)
            # - if some breeds have the same lavel of priority they are sorted in afabethical order
            
            scored_breeds = []

            for breed in self.breeds_list:
                breed_lowercase = breed.lower()
                ascii_breed_lowercase = self.to_plain_ascii(breed_lowercase)
                
                # priority 1: prefix matching
                if breed_lowercase.startswith(typed_text_lowercase):
                    start_score = 0
                    raw_score = 100
                elif ascii_breed_lowercase.startswith(ascii_typed_text_lowercase):
                    start_score = 1
                    raw_score = 100
                else:
                    start_score = 2
                    # priority 2: fuzzy matching
                    raw_score = fuzz.WRatio(ascii_typed_text_lowercase, ascii_breed_lowercase)
                    # Invert score for ascending sort (100 = 0, 90 = 10, etc.)

                if start_score == 0 or start_score == 1 or raw_score > TRESHOLD_PERCENTAGE_FUZZY_SCORE:
                    ratio_score = 100 - raw_score
                    scored_breed = ((start_score, ratio_score, ascii_breed_lowercase), breed)
                    scored_breeds.append(scored_breed)
                    
            # Sort by the tuple keys: start_score -> partial_ratio_score -> Alphabetical
            scored_breeds.sort(key=operator.itemgetter(0))
            
            # Extract just the names
            filtered_list = [item[1] for item in scored_breeds]

        for item in filtered_list:
            self.breed_listbox.insert("end", item)

    
    def on_list_select(self, event):
        # Check if there is a selection
        if not self.breed_listbox.curselection():
            return

        # Get the selected items text
        selected_index = self.breed_listbox.curselection()[0]
        selected_text = self.breed_listbox.get(selected_index)
        
        # Clear the entry box
        self.breed_entry.delete(0, "end")
        # Insert the selected text into the entry box
        self.breed_entry.insert(0, selected_text)


    # ########## FUNCTION FOR SAVING PARTICIPANT TO DISK ##########
    def add_participant(self):
        participant_id_num = self.participant_id_num_entry.get()
        breed = self.breed_entry.get()
        sex_long_name = self.sex_long_name_stringvar.get()
        neutered = self.neutered_booleanvar.get()
        age_years = self.age_years_stringvar.get()
        age_months = self.age_months_stringvar.get()
        weight_kg = self.weight_entry.get()
        hours_spent_with_owner = self.hours_with_owner_daily_stringvar.get()
        provenance_long_name = self.provenance_long_name_stringvar.get()

        # Input validation
        missing_items_error_message = []
        invalid_items_error_message = []
        error_message = []

        # Check for missing and invalid fields
        items_to_fill = []
        
        if not participant_id_num:
            items_to_fill.append(PARTICIPANT_ID_NUMBER_GUI_NAME)
        else:
            # verify if the value of participant id num is valid
            try:
                next_id_num = int(participant_id_num)
                if next_id_num < 1:
                    invalid_items_error_message.append(f"{PARTICIPANT_ID_NUMBER_GUI_NAME} must be a positive integer.")
            except ValueError:
                invalid_items_error_message.append(f"{PARTICIPANT_ID_NUMBER_GUI_NAME} must be a positive integer.")
            next_participant_id = dataset_utils.get_participant_id(next_id_num)
            if dataset_utils.participant_id_exists(next_participant_id):
                invalid_items_error_message.append(f"'{next_participant_id}' is already present in {OUTPUT_FILE_PATH}.")    

        if not breed:
            items_to_fill.append(BREED_GUI_NAME)
        elif breed not in self.breeds_list:
            invalid_items_error_message.append(f"{BREED_GUI_NAME} '{breed}' is not valid, please select one from the list.")

        if not sex_long_name:
            items_to_fill.append(SEX_GUI_NAME)
        
        if not age_years:
            items_to_fill.append(AGE_YEARS_FIELD_GUI_NAME)
        
        if not age_months:
            items_to_fill.append(AGE_MONTHS_FIELD_GUI_NAME)
        
        if age_years and age_months:
            total_age_in_months = int(age_years) * 12 + int(age_months) # Convert age to months
            if total_age_in_months < 1:
                invalid_items_error_message.append(f"Total {dataset_utils.ParticipantsColumns.AGE_IN_MONTHS.long_name} must be at least 1.")
        
        if not weight_kg:
            items_to_fill.append(WEIGHT_KG_GUI_NAME)
        else:
            weight_kg = weight_kg.replace(",", ".") # in case the user used comma as decimal separator
            try:
                weight_kg_float = float(weight_kg)
                if weight_kg_float <= 0:
                    invalid_items_error_message.append(f"{WEIGHT_KG_GUI_NAME} must be a positive number.")
            except ValueError:
                invalid_items_error_message.append(f"{WEIGHT_KG_GUI_NAME} must be a positive number.")
        
        if not hours_spent_with_owner:
            items_to_fill.append(DAILY_TIME_WITH_OWNER_H_GUI_NAME)
        
        if not provenance_long_name:
            items_to_fill.append(PROVENANCE_GUI_NAME)
        
        if items_to_fill:
            missing_items_error_message.append("\n".join(items_to_fill))
        
        # Print error messages and return if any error is found
        if invalid_items_error_message:
            error_message.append("Invalid fields:\n" + "\n".join(invalid_items_error_message))
        if missing_items_error_message:
            error_message.append("Missing fields. Please fill:\n" + "\n".join(missing_items_error_message))
        if error_message:
            messagebox.showerror("Input Error", "\n\n".join(error_message))
            return
        
        # All inputs are valid
        # Check if the dataset directory exists, if not create it
        if not os.path.exists(DATASET_ROOT):
            os.makedirs(DATASET_ROOT)
        
        
        
        dataset_utils.write_on_participants_file(
            next_participant_id, 
            PARTICIPANTS_SPECIES_LONG_NAME,
            breed, 
            sex_long_name, 
            neutered, 
            total_age_in_months, 
            weight_kg_float, 
            hours_spent_with_owner, 
            provenance_long_name
        )

        messagebox.showinfo("Success", f"Participant added: {next_participant_id}")


if __name__ == "__main__":
    root = tk.Tk()
    app = SubjectAdderApp(root)
    root.mainloop()