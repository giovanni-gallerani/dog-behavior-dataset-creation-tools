from pathlib import Path
import os
from enum import Enum
import csv
import json
import datetime
from collections import OrderedDict

SOURCE_DATASET_ROOT = Path("../sourcedata/source/")
# this is not a BIDS dataset since it also contains audio and video files
# but it is organized in a way that is easily compatible with the BIDS specification.



class MappableEnum(Enum):
    """Base class to provide lookup logic to all the Enums."""
    def __init__(self, code, long_name):
        self.code = code
        self.long_name = long_name

    @classmethod
    def list_long_names(cls) -> list[str]:
        """Returns a list of all valid full names."""
        return [item.long_name for item in cls]
    
    @classmethod
    def list_codes(cls) -> list[str]:
        """Returns a list of all valid codes."""
        return [item.code for item in cls]
    
    @classmethod
    def get_long_name(cls, code):
        """Find the long name by providing the data name (e.g., 'pres' -> 'Presession')"""
        long_name = next((item.long_name for item in cls if item.code == code), None)
        if long_name is None:
            raise ValueError(f'No long name associated with "{code}"')
        else:
            return long_name
    
    @classmethod
    def get_code(cls, long_name):
        """Find the short code by providing the long name (e.g., 'Presession' -> 'pres')"""
        code = next((item.code for item in cls if item.long_name == long_name), None)
        if code is None:
            raise ValueError(f'No code associated with "{long_name}"')
        else:
            return code



# --- Participants ---
# Example of "participants.tsv" file
# participant_id	species	breed	sex	neutered	age_months	weight_kg	daily_time_with_owner_hours	provenance
# sub-01	canis familiaris	Shiba Inu	female	True	63	7.8	10	pet store

PARTICIPANTS_FILE_PATH = Path(SOURCE_DATASET_ROOT) / "participants.tsv" # path to the file containing the list of participants
PARTICIPANTS_JSON_SIDECAR_FILE_PATH = Path(SOURCE_DATASET_ROOT) / f"participants.json"
PARTICIPANT_ID_NUMBER_LEADING_ZEROS = 2
RECORDING_TEST_PARTICIPANT_ID = f"sub-{0:0{PARTICIPANT_ID_NUMBER_LEADING_ZEROS}d}" # used for testing and debugging purposes
ALL_DOGS_BREEDS_FILE_PATH = Path("./all_dogs_breeds.txt")

# attributes used in participants.tsv
class ParticipantsColumns(MappableEnum):
    # Format: NAME = (Code, Long Name)
    PARTICIPANT_ID = ("participant_id", "Participant identifier")
    SPECIES = ("species", "Species")
    BREED = ("breed", "Breed")
    SEX = ("sex", "Sex")
    NEUTERED = ("neutered", "Neutered")
    AGE_IN_MONTHS = ("age_months", "Age (months)")
    WEIGHT_KG = ("weight_kg", "Weight (kg)")
    DAILY_TIME_WITH_OWNER_H = ("daily_time_with_owner_hours", "Daily time with owner (hours)")
    PROVENANCE = ("provenance", "Provenance")

class SpeciesLevels(MappableEnum):
    # Format: NAME = (Code, Long Name)
    DOG = ("canis familiaris", "Domestic dog")

# function used for calculating breeds levels when writing metadata in json file
def get_all_dogs_breeds_list() -> list[str]:
    """returns a list of all dog breeds contained in the file ALL_DOGS_BREEDS_FILE_PATH"""
    with open(ALL_DOGS_BREEDS_FILE_PATH, "r", encoding="utf-8") as all_dog_breeds_file:
        return [line.strip() for line in all_dog_breeds_file if line.strip()]

class SexLevels(MappableEnum):
    # Format: NAME = (Code, Long Name)
    MALE   = ("male", "Male")
    FEMALE = ("female", "Female")

class NeuteredLevels(MappableEnum):
    # Format: NAME = (Code, Long Name)
    # Note: Using boolean values as name in data
    NEUTERED = (True, "Neutered or spayed")
    INTACT   = (False, "Not neutered or spayed")

class ProvenanceLevels(MappableEnum):
    # Format: NAME = (Code, Long Name)
    PET_STORE      = ("pet store", "Obtained from a pet store")
    PRIVATE_BREEDER = ("private breeder", "Obtained from a private breeder")
    SHELTER        = ("animal shelter", "Obtained from an animal shelter")
    ANIMAL_RESCUE  = ("animal rescue organization", "Obtained from an animal rescue organization")
    SELF_BRED      = ("self bred", "Bred by the current owner")
    OTHER_OWNER    = ("other owner", "Obtained from other owner")
    FOUND_AS_STRAY = ("found as a stray", "Found as a stray")
    OTHER          = ("other", "Other provenance")

# File position and naming for participants
def get_participant_id(participant_id_num: int) -> str:
    """
    Given an integer, verify that it is >= and return the participant_id related to it.
    Example: 1 -> sub-01
    """
    if type(participant_id_num) != int:
        raise ValueError(f"{ParticipantsColumns.PARTICIPANT_ID.long_name} Number must be an integer >= 0")
    if participant_id_num < 0:
        raise ValueError(f"{ParticipantsColumns.PARTICIPANT_ID.long_name} Number must be an integer >= 0")
    return f"sub-{participant_id_num:0{PARTICIPANT_ID_NUMBER_LEADING_ZEROS}d}"

def validate_participant_id(participant_id: str):
    """Utility function used for validating a given participant id, tells if it is formatted correctly"""
    sub_prefix, participant_label = participant_id.split("-")
    if (sub_prefix != "sub") or (not participant_label.isdigit()) or (not int(participant_label) >= 0):
        raise ValueError(f'{ParticipantsColumns.PARTICIPANT_ID.long_name} must be in the format "sub-<label>". <label> is an integer >= 0')
    
def get_participant_dir(participant_id: str) -> Path:
    try:
        validate_participant_id(participant_id)
        return SOURCE_DATASET_ROOT / participant_id
    except ValueError as e:
        raise ValueError(f"Error while calculating participant directory: {e}")

# Function for writing partcipants.tsv file
def write_on_participants_file(participant_id: str, species_long_name: str, breed: str, sex_long_name: str, neutered: bool, age_in_months: int, weigth_kg: float, hours_spent_with_owner: int, provenance_long_name: str):
    """writes participant into participants.tsv file"""
    try:
        validate_participant_id(participant_id)
        species = SpeciesLevels.get_code(species_long_name)
        sex = SexLevels.get_code(sex_long_name)
        provenance = ProvenanceLevels.get_code(provenance_long_name)
    except ValueError as e:
        raise ValueError(f"Error while writing on the participants file: {e}")

    participant_data = [participant_id, species, breed, sex, neutered, age_in_months, weigth_kg, hours_spent_with_owner, provenance]
    # create output file if it does not exist, also add header
    if not PARTICIPANTS_FILE_PATH.exists():
        with open(PARTICIPANTS_FILE_PATH, "w", newline="") as tsv_file:
            tsv_writer = csv.writer(tsv_file, delimiter="\t")
            header = ParticipantsColumns.list_codes()
            tsv_writer.writerow(header)
    # Append the new subject to the TSV file
    with open(PARTICIPANTS_FILE_PATH, "a", newline="", encoding='utf-8') as tsv_file:            
        tsv_writer = csv.writer(tsv_file, delimiter="\t")
        tsv_writer.writerow(participant_data)
    if not PARTICIPANTS_JSON_SIDECAR_FILE_PATH.exists():
        write_participants_json_sidecar()

# Function for writing participants.json file
def write_participants_json_sidecar():
    """Function for writing metadata related to the participants.tsv file"""
    breed_levels = {}
    breed_list = get_all_dogs_breeds_list()
    for breed in breed_list:    
        breed_levels[breed] = breed
    content = {
        ParticipantsColumns.PARTICIPANT_ID.code: {
            "LongName": ParticipantsColumns.PARTICIPANT_ID.long_name,
            "Description": "Unique participant identifier",
            "Format": "string"
        },
        ParticipantsColumns.SPECIES.code: {
            "LongName": ParticipantsColumns.SPECIES.long_name,
            "Description": "Biological species of the participant",
            "Format": "string",
            "Levels": {l.code : l.long_name for l in SpeciesLevels}
        },
        ParticipantsColumns.BREED.code: {
            "LongName": ParticipantsColumns.BREED.long_name,
            "Description": "Dog breed as reported by the breeder or shelter",
            "Format": "string",
            "Levels": breed_levels
        },
        ParticipantsColumns.SEX.code: {
            "LongName": ParticipantsColumns.SEX.long_name,
            "Description": "Biological sex of the participant",
            "Format": "string",
            "Levels": {l.code : l.long_name for l in SexLevels}
        },
        ParticipantsColumns.NEUTERED.code: {
            "LongName": ParticipantsColumns.NEUTERED.long_name,
            "Description": "Whether the participant has been neutered or spayed",
            "Format": "string",
            "Levels": {l.code : l.long_name for l in NeuteredLevels}
        },
        ParticipantsColumns.AGE_IN_MONTHS.code: {
            "LongName": ParticipantsColumns.AGE_IN_MONTHS.long_name,
            "Description": "Age of the participant at the time of the study expressed in months",
            "Format": "integer",
            "Units": "months",
            "Minimum": 0
        },
        ParticipantsColumns.WEIGHT_KG.code: {
            "LongName": ParticipantsColumns.WEIGHT_KG.long_name,
            "Description": "Body weight of the participant at the time of the study expressed in kg",
            "Format": "number",
            "Units": "kilograms",
            "Minimum": 0.1
        },
        ParticipantsColumns.DAILY_TIME_WITH_OWNER_H.code: {
            "LongName": ParticipantsColumns.DAILY_TIME_WITH_OWNER_H.long_name,
            "Description": "Amount of time in hours, that the participant dog spends on average with its owner per day",
            "Format": "integer",
            "Units": "hours",
            "Minimum": 0,
            "Maximum": 24
        },
        ParticipantsColumns.PROVENANCE.code: {
            "LongName": ParticipantsColumns.PROVENANCE.long_name,
            "Description": "Origin of the participant prior to inclusion in the study",
            "Format": "string",
            "Levels": {l.code : l.long_name for l in ProvenanceLevels}
        }
    }
    with open(PARTICIPANTS_JSON_SIDECAR_FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=4) # ensure_ascii=False for writing of unicode characters

# Utilities functions related to participants.tsv creation and management
def list_participants_summary():
    """
    Utility function to list all available partcipants with some details for easier identification as a list of strings.
    The separator ':' is used between Participant identifier and the summary of its data.
    Output example: ["sub-01: Shiba Inu, female, 3y 2m", "sub-02: Golden Retriever, male, 5y 0m"]
    """
    if not PARTICIPANTS_FILE_PATH.exists():
        return []
    with open(PARTICIPANTS_FILE_PATH, "r", newline='', encoding="utf-8") as f:
        tsv_reader = csv.DictReader(f, delimiter="\t")
        participants_summary = [f'{row[ParticipantsColumns.PARTICIPANT_ID.code]}: {row[ParticipantsColumns.BREED.code]}, {row[ParticipantsColumns.SEX.code]}, {int(row[ParticipantsColumns.AGE_IN_MONTHS.code])//12}y {int(row[ParticipantsColumns.AGE_IN_MONTHS.code])%12}m' for row in tsv_reader]
    participants_summary.sort()
    return participants_summary

def participant_id_exists(participant_id: str) -> bool:
    "return wheter a given participant id is present in the participants file"   
    validate_participant_id(participant_id)
    if not PARTICIPANTS_FILE_PATH.exists():
        return False
    with open(PARTICIPANTS_FILE_PATH, "r", newline="", encoding='utf-8') as tsv_file:
        tsv_reader = csv.reader(tsv_file, delimiter="\t")
        file_rows = list(tsv_reader)
        # Determine the already present participants
        if len(file_rows) == 1:
            # this means there is only the header, so there are no participants in the file, so for sure participant id num is not used
            return False
        # skip the header, get all the ids of the participant_id from the file
        # then check if the participant_id is in the array
        existing_participants_id = [row[0] for row in file_rows[1:]]
        if participant_id in existing_participants_id:
            return True
        return False

def calculate_next_participant_id_num() -> int:
    "returns the next unused participant id number"
    starting_participant_id_num = 1
    if not PARTICIPANTS_FILE_PATH.exists():
        return starting_participant_id_num
    with open(PARTICIPANTS_FILE_PATH, "r", newline="", encoding='utf-8') as tsv_file:
        tsv_reader = csv.reader(tsv_file, delimiter="\t")
        file_rows = list(tsv_reader)
        if len(file_rows) == 1:
            # this means there is only the header, so participant_id = 1
            return starting_participant_id_num
        # skip the header, get all the ids of the participant_id from the file, the next participant_id must be max_id + 1
        return max([int(row[0].split('-')[1]) for row in file_rows[1:]]) + 1


# --- Sessions ---
class SessionsColumns(MappableEnum):
    # Format: NAME = (Code, Long Name)
    SESSION_ID = ("session_id", "Session identifier")
    ACQUISITION_TIME = ("acq_time", "Acquisition time")

class SessionTypes(MappableEnum): # used inside the session_id
    # Format: NAME = (Code, Long Name)
    PRESESSION = ("pres", "Presession")
    SCENARIOS   = ("scens", "Scenarios sequence")

SESSION_ID_NUMBER_LEADING_ZEROS = 2 # number of leading zeros used in session_id label (e.g. with 2 leading zeros session id could be ses-pres01)

def get_session_id(session_type_long_name: str, session_id_num: int) -> str:
    try:
        session_type_code = SessionTypes.get_code(session_type_long_name)
    except ValueError as e:
        raise ValueError(f"Error in calculating {SessionsColumns.SESSION_ID.long_name}: {e}")
    if session_id_num < 1:
        raise ValueError(f"Error in calculating {SessionsColumns.SESSION_ID.long_name}: session_id_num must be > 0")
    return f"ses-{session_type_code}{session_id_num:0{SESSION_ID_NUMBER_LEADING_ZEROS}d}"

def get_session_dir(participant_id: str, session_type_long_name: str, session_id_num: int) -> Path:
    """Utility function to calculate the output directory path where the data will be saved on the receivers
    Example path for a recording: DOG_BEHAVIOR_DATASET/sub-01/ses-pres01/"""
    try:
        participant_dir =  get_participant_dir(participant_id)
        session_id = get_session_id(session_type_long_name, session_id_num)
        return participant_dir / session_id
    except ValueError as e:
        raise ValueError(f"Error while calculating session directory: {e}")

def calculate_next_session_id_num(participant_id: str, session_type_long_name: str) -> int:
    """Utility function to calculate the next session id number."""
    participant_dir = get_participant_dir(participant_id)
    session_type_code = SessionTypes.get_code(session_type_long_name)
    session_id_number = None
    # if the participant directory, or a session directory of the same session type, does not exist the session number will be 1
    if not participant_dir.exists():
        session_id_number = 1
    else:
        # list the existing session directories of the same session type founded inside the participant directory
        existing_dirs_of_current_session_type = [d for d in os.listdir(participant_dir) if (participant_dir / d).is_dir() and d.startswith(f"ses-{session_type_code}")]
        if existing_dirs_of_current_session_type == []:
            # no directories of the same session type are present, session number is 1.
            session_id_number = 1
        else:
            # directories of the same session type are present, session_number will be the next number available
            # extract the session number from the existing directories names
            # e.g., "ses-pres01" -> 1
            # Then use the next highest number (e.g. if 1,2,4 exist, use 5) 
            session_id_number = max([int(d.split("-")[1][len(session_type_code):]) for d in existing_dirs_of_current_session_type]) + 1
    return session_id_number



# --- Tasks ---
# code is used in file names
# long name is TaskName in the metadata fiels in beh/ folder
class TaskTypes(MappableEnum):
    # Format: NAME = (Code, Long Name)
    CALIBRATION   = ("calib", "Calibration")
    RESTING       = ("rest", "Resting")
    CONVERSATION  = ("conversation", "Conversation with the Owner")
    TREAT         = ("treat", "Receiving Treat")

def get_task_id(task_long_name: str):
    try:
        task_code = TaskTypes.get_code(task_long_name)
        return f"task-{task_code}"
    except ValueError as e:
        raise ValueError(f"Error in calculating Task ID: {e}")



# --- Output Files Prefix ---
def get_output_filename_prefix(participant_id: str, session_type_long_name: str, session_id_num: int, task_long_name: str) -> str:
    """return the prefix common to all the files obtained in the same participant session with the participant performing a specific task"""
    try:
        validate_participant_id(participant_id)
        session_id = get_session_id(session_type_long_name, session_id_num)
        task_id = get_task_id(task_long_name)
        return f"{participant_id}_{session_id}_{task_id}"
    except ValueError as e:
        raise ValueError(f"Error in calculating output filename prefix: {e}")



# --- Run ---
def get_run_id(run_index: int) -> str:
    if type(run_index) != int:
        raise ValueError("Run Index must be a positive integer")
    if run_index < 1:
        raise ValueError("Run Index must be a positive integer")
    return f"run-{run_index}"

def calculate_next_run_index(participant_id: str, session_type_long_name: str, session_id_num: int, task_long_name: str) -> int:
    """
    Utility function for calculating the next run index.
    If the ouput directory is not found run index is 1.
    Otherwise return the highest index + 1
    """
    try:
        session_dir = get_session_dir(participant_id, session_type_long_name, session_id_num)
    except ValueError as e:
        raise ValueError(f"Error while calculating next run index: {e}")
    if not session_dir.exists():
        return 1
    output_dir = session_dir / "video" # the video folder is used since for sure data goes into it
    # inside the output dir, search for files that have the same use task code in the filename
    # if there are none, run index is 1, otherwhise is the max run + 1
    next_run_index = None
    filename_prefix = get_output_filename_prefix(participant_id, session_type_long_name, session_id_num, task_long_name)
    existing_filenames_with_same_prefix = [f for f in os.listdir(output_dir) if (output_dir / f).is_file() and f.startswith(filename_prefix)]
    if existing_filenames_with_same_prefix == []:
        # no files with the same prefix, run is 1
        next_run_index = 1
    else:
        # for each file isolate the run-XX element in the filename
        # the next run index will the the max + 1
        existing_run_indexes = []
        for f in existing_filenames_with_same_prefix:
            for element in f.split("_"):
                if element.startswith("run-"):
                    existing_run_indexes.append(int(element[len("run-"):]))
        next_run_index = max(existing_run_indexes) + 1
    return next_run_index

def run_already_exists(participant_id: str, session_type_long_name: str, session_id_num: int, task_long_name: str, run_index: int):
    # first check if the run_index is valid
    try:
        run_index_int = int(run_index)
    except ValueError:
        raise ValueError(f"Error while checking for run existence: {e}")
    if run_index_int < 1:
        raise ValueError(f"Error while checking for run existence: run_index must be > 0")
    # calculate session dir where the run should be
    try:
        session_dir = get_session_dir(participant_id, session_type_long_name, session_id_num)
    except ValueError as e:
        raise ValueError(f"Error while checking for run existence: {e}")
    if not session_dir.exists():
        return False # if the session directory does not exists for sure that run does not
    # calculate output dir
    output_dir = session_dir / "video" # the video folder is used since for every run videos are always recorded, so for sure the run files are in it #TODO: if in the future there will be runs without video, we should change this to "beh" or other more general folder
    # search for file with the same prefix and run in the output dir
    try:
        filename_prefix = get_output_filename_prefix(participant_id, session_type_long_name, session_id_num, task_long_name)
    except ValueError as e:
        pass
    existing_filenames_with_same_prefix = [f for f in os.listdir(output_dir) if (output_dir / f).is_file() and f.startswith(filename_prefix)]
    if existing_filenames_with_same_prefix == []:
        return False
    existing_run_indexes = []
    for f in existing_filenames_with_same_prefix:
        for element in f.split("_"):
            if element.startswith("run-"):
                existing_run_indexes.append(int(element[len("run-"):]))
    # if the index is present in the list of already existing files with the same prefix return True
    return run_index_int in existing_run_indexes


# DEBUG TESTS
#print(get_output_filename_prefix("sub-01", "Presession", 1, "Free Behavior"))
#print(get_session_dir("sub-01", "Presession", 1))
#print(calculate_next_run_index("sub-01", "Presession", 1, "Free Behavior"))


# =========================================================
# Modality Agnostic Files - Dataset Description
# =========================================================
# This is not used since the source data is saved in a non BIDS dataset, but it is left here for reference and future use in case we want to create a BIDS derivative dataset starting from the source data.


# =========================================================
# Modality Agnostic Files - Data Summary Files
# =========================================================

# --- Scans files -----------------------------------------------------------------------------------------------------

class ScansColumns(MappableEnum):
    # Format: NAME = (Code, Long Name)
    FILENAME = ("filename", "Filename")
    ACQUISITION_TIME = ("acq_time", "Acquisition time")

# sub-<label>_ses-<label>_scans.tsv
def write_on_scans_tsv(participant_id: str, session_id: str, scans_list: list[dict]):
    """
    Register filename and acq_time inside sub-<label>_ses-<label>_scans.tsv in the session directory.
    scans_list is a list of dictionaries with keys: 'filename' and 'acq_time'.
    The path in filename must use '/' as separator independently of the operative system, and must be relative to the session directory, since this is the format required in the _scans.tsv file.
    The acq_time must be expressed in datetime isoformat, since this is the format required in the _scans.tsv file.
    """
    session_dir = get_participant_dir(participant_id) / session_id
    scans_file_path = session_dir / f"{participant_id}_{session_id}_scans.tsv"
    fieldnames = ScansColumns.list_codes()
    # note that scans metadata file uses relative paths in a columns called filename
    # the scan_metadata list contains absolute paths, so we need to convert them to relative paths before writing
    
    # check if the metadata file already exists
    file_exists = scans_file_path.exists()

    with open(scans_file_path, "a", newline='', encoding="utf-8") as f:
        tsv_writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        # if the file does not exist write the header
        if not file_exists:
            tsv_writer.writeheader()
        # write the new entry
        for scan in scans_list:
            tsv_writer.writerow({
                # since filename must be relative to the session directory, use only the name of the file and the directory it is in
                ScansColumns.FILENAME.code: str(scan["file_path"]).replace(str(session_dir) + os.sep, "").replace(os.sep, "/"), # replace os.sep with '/' to have the correct format in the _scans.tsv file independently of the operative system
                ScansColumns.ACQUISITION_TIME.code: scan["acq_time"] # acq_time is expressed in datetime isoformat
            })

# scans.json
# Following the inheritance principle https://bids-specification.readthedocs.io/en/latest/common-principles.html#the-inheritance-principle
# A single scans.json, without any entity in the filename at the top level, is applicable to describe columns of any other _scans.tsv potentially present in the dataset for other subjects.
def write_scans_json_sidecar(dataset_root: Path):
    """Function for writing metadata related to the _scans.tsv files in the dataset root directory"""
    dataset_root = Path(dataset_root)
    if not dataset_root.exists() or not dataset_root.is_dir():
        raise ValueError(f"Error in writing scans.json file: dataset root {dataset_root} does not exist or is not a directory")
    content = {
        ScansColumns.FILENAME.code: {
            "LongName": ScansColumns.FILENAME.long_name,
            "Description": "Relative paths to the associated file. Paths are relative to the session directory. Uses '/' as separator independently of the operative system"
        },
        ScansColumns.ACQUISITION_TIME.code: {
            "LongName": ScansColumns.ACQUISITION_TIME.long_name,
            "Description": "Acquisition time of the first data point of the file"
        }
    }
    scans_json_sidecar_file_path = dataset_root / "scans.json"
    with open(scans_json_sidecar_file_path, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=4) # ensure_ascii=False for writing of unicode characters


# --- Sessions files -----------------------------------------------------------------------------------------------------
def calculate_session_acq_time(session_dir: Path) -> float:
    """
    Calculate the acquisition time of the session given the session directory path.
    The session acquisition time is the minimum acquisition time of the files in the scans file of the session.
    """
    session_dir = Path(session_dir)
    if not session_dir.exists() or not session_dir.is_dir():
        raise ValueError(f"Error in calculating acquisition time of the session: session directory {session_dir} does not exist or is not a directory")
    scans_file_path = next(file for file in session_dir.iterdir() if file.name.endswith("_scans.tsv"))
    if not scans_file_path:
        raise FileNotFoundError(f"No scans file found in {session_dir}")
    with open(scans_file_path, 'r', newline="", encoding='utf-8') as tsv_file:
        tsv_reader = csv.DictReader(tsv_file, delimiter="\t")
        acq_times = []
        for row in tsv_reader:
            try:
                # obtain the acquisition time in seconds since the epoch, using the datetime module to parse the isoformat string in the acq_time column of the _scans.tsv file
                acq_time = datetime.datetime.fromisoformat(row[ScansColumns.ACQUISITION_TIME.code])
                acq_times.append(acq_time)
            except (ValueError, IndexError):
                continue
        if not acq_times:
            raise ValueError(f"Error in calculating acquisition time of the session: no valid acquisition time found in the scans file {scans_file_path}")
        return (min(acq_times)).isoformat() # return the minimum acquisition time and convert it back to isoformat


# sub-<label>_sessions.tsv
def write_sessions_tsv_in_participant_dir(participant_dir: Path):
    """Function for writing _session.tsv file related to a given participant directory"""
    participant_dir = Path(participant_dir)
    if not participant_dir.exists() or not participant_dir.is_dir():
        raise ValueError(f"Error in writing sessions.tsv file: participant directory {participant_dir} does not exist or is not a directory")
    sessions = []
    for session_dir in participant_dir.iterdir():
        if session_dir.is_dir() and session_dir.name.startswith("ses-"):
            try:
                session_acq_time = calculate_session_acq_time(session_dir)
                sessions.append({
                    SessionsColumns.SESSION_ID.code: session_dir.name,
                    SessionsColumns.ACQUISITION_TIME.code: session_acq_time
                })
            except ValueError as e:
                print(f"Warning: {e}")
    # since the order of the object returned by participant_dir.iterdir() is not guaranteed, sort the sessions by session id
    alphatetically_sorted_sessions = sorted(sessions, key=lambda x: x[SessionsColumns.SESSION_ID.code])
    # after having calculated the session acquisition times for each of the subject's sessions, write the sessions.tsv file in the participant directorym
    sessions_file_path = participant_dir / f"{participant_dir.name}_sessions.tsv"
    with open(sessions_file_path, 'w', newline="", encoding='utf-8') as tsv_file:
        fieldnames = SessionsColumns.list_codes()
        tsv_writer = csv.DictWriter(tsv_file, fieldnames=fieldnames, delimiter="\t")
        tsv_writer.writeheader()
        for session in alphatetically_sorted_sessions:
            tsv_writer.writerow(session)


# sessions.json
# Following the inheritance principle https://bids-specification.readthedocs.io/en/latest/common-principles.html#the-inheritance-principle
# A single sessions.json, without any entity in the filename at the top level, is applicable to describe columns of any other _sessions.tsv potentially present in the dataset for other subjects.
def write_sessions_json_sidecar(dataset_root: Path):
    """Function for writing metadata related to the _sessions.tsv files in the dataset root directory"""
    content = {
        SessionsColumns.SESSION_ID.code: {
            "LongName": SessionsColumns.SESSION_ID.long_name,
            "Description": "Session ID"
        },
        SessionsColumns.ACQUISITION_TIME.code: {
            "LongName": SessionsColumns.ACQUISITION_TIME.long_name,
            "Description": "Acquisition time of the first data point of the session"
        }
    }
    sessions_json_file_path = dataset_root / "sessions.json"
    with open(sessions_json_file_path, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=4) # ensure_ascii=False for writing of unicode characters

# =========================================================
# Modality Specific Files
# =========================================================
def calculate_file_start_time(file_path: Path) -> float:
    """
    Calculate the start time of a data file relative to the start of the run it was created in.
    Calculate the start time of the run, compare it with the starting time for the file in scans file.
    The difference between the two is the start time of the file relative to the start of the run, 
    expressed in seconds with fractional part, e.g. 12.5 means that the recording started 12 seconds and 500 milliseconds after the beginning of the run.
    """
    # ensure that the path is a Path object and that the file exists, otherwise raise an error
    file_path = Path(file_path)
    if not file_path.exists():
        raise ValueError(f"Error in calculating start time of the file: file {file_path} does not exist")
    session_dir = file_path.parent.parent
    scans_file_path = next(file for file in session_dir.iterdir() if file.name.endswith("_scans.tsv"))
    with open(scans_file_path, 'r', newline="", encoding='utf-8') as tsv_file:
        tsv_reader = csv.DictReader(tsv_file, delimiter="\t")
        scans_file_rows = list(tsv_reader)
        # determine the file run id
        run_id = None
        for element in file_path.stem.split("_"):
            if element.startswith("run-"):
                run_id = element
                break
        if run_id is None:
            raise ValueError(f"Error in calculating start time of the file: the filename {file_path.name} does not contain a run-XX element")
        # filter the rows of the scans file to find the ones where the filename column has the same run id as the given file
        scans_file_rows_of_same_run = [row for row in scans_file_rows if run_id in row[ScansColumns.FILENAME.code]]
        if len(scans_file_rows_of_same_run) == 0:
            raise ValueError(f"Error in calculating start time of the file: no row in the scans file {scans_file_path} contains the run {run_id} of the file {file_path.name}")
        # the acquisition time of the run is minimum value of the acq_time column of the rows in scans_file_rows_of_same_run
        acq_times = []
        for row in scans_file_rows_of_same_run:
            try:
                # obtain the acquisition time in seconds since the epoch, using the datetime module to parse the isoformat string and convert it to timestamp
                acq_time = datetime.datetime.fromisoformat(row[ScansColumns.ACQUISITION_TIME.code]).timestamp()
                acq_times.append(acq_time)
            except (ValueError, IndexError):
                continue
        if not acq_times:
            raise ValueError(f"Error in calculating start time of the file: no valid acquisition time found in the scans file {scans_file_path} for run {run_id}")
        run_start_time = min(acq_times)
        # calculate the acquisition time of the physio file relative to the run start time.
        file_acq_time = None
        for row in scans_file_rows_of_same_run:
            if file_path.name in row["filename"]:
                try:
                    file_acq_time = datetime.datetime.fromisoformat(row["acq_time"]).timestamp()
                except (ValueError, IndexError):
                    continue
                break
        if file_acq_time is None:
            raise ValueError(f"Error in calculating start time of the file: no acquisition time found for file {file_path.name} in scans file {scans_file_path}")
        # return the difference between the acquisition time of the physio file and the run start time, expressed in seconds with fractional part
        # round and return the result with 6 decimal digits since are the one used by isoformat for consistency
        return round(file_acq_time - run_start_time, 6)


# DEBUG TESTS
#print(calculate_file_start_time("/home/giovanni/Desktop/DOG_BEHAVIOR_STUDIO/sourcedata/sub-01/ses-scens01/physio/sub-01_ses-scens01_task-treat_run-1_recording-ecg_physio.tsv.gz"))
#print(calculate_file_start_time("/home/giovanni/Desktop/DOG_BEHAVIOR_STUDIO/sourcedata/sub-01/ses-scens01/video/sub-01_ses-scens01_task-treat_run-1_recording-cam1_video.mp4"))


# <...>_recording-ecg_physio.json (Physiological Recordings json sidecar file)
class EcgPhysioColumns(MappableEnum):
    # Format: NAME = (Code, Long Name)
    TIMESTAMP = ("timestamp", "Timestamp of the ECG recording in seconds")
    ECG_1 = ("ecg_1", "Signal from ECG elctrode 1")
    ECG_2 = ("ecg_2", "Signal from ECG elctrode 2")

def write_recording_ecg_physio_json_sidecar(ecg_physio_file_path: Path):
    """Function for writing metadata related to a recording-ecg_physio.tsv.gz file, start time must be given as input.
    It is considered the start time relative to the earliest recording start time of the run.
    If it's 0.0 it means that the ecg data was the first data point to be recorded in the run.
    if it's 5000 it means that the ecg recording started 5 seconds after the beginning of the run, and so on.
    The json sidecar file is written in the same directory of the original tsv.gz file and with the same name but with .json extension instead of .tsv.gz.
    """
    start_time_relative_to_begin_of_run = 0.001
    content = {
        "SamplingFrequency": 100.0, # 100Hz sampling frequency for ECG data
        "StartTime": start_time_relative_to_begin_of_run, # start time is relative to the start of the run when the file was recorded, it is expressed in seconds with fractional part, e.g. 12.5 means that the recording started 12 seconds and 500 milliseconds after the beginning of the run
        "Columns": EcgPhysioColumns.list_codes(),
        "PhysioType": "generic",

        # "DeviceSerialNumber": "123",	# OPTIONAL	string	The serial number of the equipment that produced the measurements. A pseudonym can also be used to prevent the equipment from being identifiable, so long as each pseudonym is unique within the dataset.
        # "Manufacturer": "TUAT",	# OPTIONAL	string	Manufacturer of the equipment that produced the measurements.
        # "ManufacturersModelName": "mpu",	# OPTIONAL	string	Manufacturer's model name of the equipment that produced the measurements.
        # "SoftwareVersions": "1.0",	# OPTIONAL	string	Manufacturer's designation of software version of the equipment that produced the measurements.
        
        EcgPhysioColumns.TIMESTAMP.code: {
            "LongName": EcgPhysioColumns.TIMESTAMP.long_name,
            "Description": "Timestamp of the ECG recording, expressed in millisecond, starting from the moment the first data point of the recording was acquired. The first timestamp is 0.0",
            "Format": "number",
            "Units": "seconds since the beginning of the recording",
            "Minimum": 0.0,
        },
        EcgPhysioColumns.ECG_1.code: {
            "LongName": EcgPhysioColumns.ECG_1.long_name,
            "Description": "continuous ECG recording 1",
            "Format": "number",
            "Units": "mV"
        },
        EcgPhysioColumns.ECG_2.code: {
            "LongName": EcgPhysioColumns.ECG_2.long_name,
            "Description": "continuous ECG recording 2",
            "Format": "number",
            "Units": "mV"
        }
    }
    json_filepath = str(ecg_physio_file_path).replace(".tsv.gz", ".json")
    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=4) # ensure_ascii=False for writing of unicode characters

# DEBUG TESTS
#write_recording_ecg_physio_json_sidecar("/home/giovanni/Desktop/DOG_BEHAVIOR_STUDIO/sourcedata/sub-01/ses-scens01/physio/sub-01_ses-scens01_task-treat_run-1_recording-ecg_physio.tsv.gz")


def write_metadata_mpu_motion_json(mpu_motion_file_path: Path):
    """Function for writing metadata related to a recording-mpu_motion.tsv file."""
    mpu_motion_file_path = Path(mpu_motion_file_path)
    if not mpu_motion_file_path.exists():
        raise ValueError(f"Error in adding metadata to the file: file {mpu_motion_file_path} does not exist")
    
    for element in mpu_motion_file_path.stem.split("_"):
        if element.startswith("task-"):
            task_id = element
            task_name = TaskTypes.get_long_name(task_id[len("task-"):])
            break

    content = {
        "SamplingFrequency": 300.0,
        "SamplingFrequencyUnit": "Hz",
        "TaskName": task_name,
        
        # Hardware information
        # "DeviceSerialNumber": "123",	# OPTIONAL	string	The serial number of the equipment that produced the measurements. A pseudonym can also be used to prevent the equipment from being identifiable, so long as each pseudonym is unique within the dataset.
        # "Manufacturer": "TUAT",	# OPTIONAL	string	Manufacturer of the equipment that produced the measurements.
        # "ManufacturersModelName": "mpu",	# OPTIONAL	string	Manufacturer's model name of the equipment that produced the measurements.
        # "SoftwareVersions": "1.0",	# OPTIONAL	string	Manufacturer's designation of software version of the equipment that produced the measurements.
        
        # Institution information
        "InstitutionName": "TUAT",	# OPTIONAL	string	Name of the institution where the measurements were taken.
        "InstitutionAddress": "Japan, Tokyo, Koganei",	# OPTIONAL	string	Address of the institution where the measurements were taken.
        "InstitutionalDepartmentName": "Department of Computer Engineering",	# OPTIONAL	string	Name of the department of the institution where the measurements were taken.
    }
    json_filepath = str(mpu_motion_file_path).replace(".tsv", ".json")
    with open(json_filepath, 'w', encoding='utf-8') as f:
        json.dump(content, f, ensure_ascii=False, indent=4) # ensure_ascii=False for writing of unicode characters
    
    
    channels_filepath = str(mpu_motion_file_path).replace("motion.tsv", "channels.tsv")
    with open(channels_filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")

        # Header
        writer.writerow(["name", "component", "type", "tracked_point", "units"])

        # Latency
        writer.writerow(["timestamp", "n/a", "LATENCY", "n/a", "s"])

        # MPU1
        writer.writerow(["mpu1_ax", "x", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu1_ay", "y", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu1_az", "z", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu1_gx", "x", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu1_gy", "y", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu1_gz", "z", "GYRO", "chest", "rad/s"])

        # MPU2
        writer.writerow(["mpu2_ax", "x", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu2_ay", "y", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu2_az", "z", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu2_gx", "x", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu2_gy", "y", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu2_gz", "z", "GYRO", "chest", "rad/s"])

        # MPU3
        writer.writerow(["mpu3_ax", "x", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu3_ay", "y", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu3_az", "z", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu3_gx", "x", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu3_gy", "y", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu3_gz", "z", "GYRO", "chest", "rad/s"])

        # MPU4
        writer.writerow(["mpu4_ax", "x", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu4_ay", "y", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu4_az", "z", "ACCEL", "chest", "m/s^2"])
        writer.writerow(["mpu4_gx", "x", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu4_gy", "y", "GYRO", "chest", "rad/s"])
        writer.writerow(["mpu4_gz", "z", "GYRO", "chest", "rad/s"])


# ANNOTATE DATASET
def annotate_dataset(dataset_root: Path):
    """
    Function for annotating a given BIDS-like dataset.
    The acquisition time assigned to each session in the sessions file is the minimum acquisition time in the scans file of that session.
    """
    dataset_root = Path(dataset_root)
    if not dataset_root.exists() or not dataset_root.is_dir():
        raise ValueError(f"Error in writing sessions.tsv files: dataset root {dataset_root} does not exist or is not a directory")    
    
    # add the metadata for scans files in the dataset root directory, since it is applicable to all the _scans.tsv files already present in the dataset
    write_scans_json_sidecar(dataset_root)
    print("Added \"scans.json\" sidecar file in the dataset root directory")
    
    # for each participant directory write the sessions.tsv file with the session acquisition times calculated from the scans files.
    for item in sorted(dataset_root.iterdir()):
        if item.is_dir() and item.name.startswith("sub-"):
            write_sessions_tsv_in_participant_dir(item)
            print(f"Added \"{item.name}_sessions.tsv\" file in {item}")
    
    # after having written all the sessions.tsv files write the sessions.json sidecar file in the dataset root directory, since it is applicable to all the _sessions.tsv files in the dataset
    write_sessions_json_sidecar(dataset_root)
    print("Added \"sessions.json\" sidecar file in the dataset root directory")

    # now explore the dataset and add metadata to all physio and motion files
    for item in sorted(dataset_root.iterdir()):
        if item.is_dir() and item.name.startswith("sub-"):
            for session_dir in item.iterdir():
                if session_dir.is_dir() and session_dir.name.startswith("ses-"):
                    for datatype_dir in session_dir.iterdir():
                        if datatype_dir.is_dir():
                            for file in datatype_dir.iterdir():
                                if file.is_file() and file.name.endswith("recording-ecg_physio.tsv.gz"):
                                    write_recording_ecg_physio_json_sidecar(file)
                                    print(f"Added json sidecar file for {file}")
                                if file.is_file() and "_tracksys-mpu_" in file.name and file.name.endswith("_motion.tsv"):
                                    write_metadata_mpu_motion_json(file)
                                    print(f"Added json sidecar file for {file}")