# Dog Behavior Study Dataset Creation Tools

## 1. Introduction
This repository contains the work completed in the context of my master's thesis research at [TUAT (Tokyo University of Agriculture and Technology)](https://www.tuat.ac.jp/en/), specifically for the [TUAT Biosignal Informatics Laboratory](https://www.sip.tuat.ac.jp/).  

This repository folder is intended as a BIDS dataset that can be populated by using the given tools
The content of this repository is divided as follows:

- **`docs/`**: contains the full pdf of the thesis and the adopted dataset structure for consultation.
- **`code/`**: contains the code developed for acquiring data from the sensors and adding the correct metadata.

The project is still evolving, the latest code can be found in the TTLab official repository at this [link](https://github.com/ttlabtuat/DOG_BEHAVIOR_STUDY_DATASET.git). Note that the linked repository could be closed at public while the development continues, in that case you have to ask permission for seeing its content.  

## 2. Installing requirements
1.  **Create a Virtual Environment:** It's highly recommended to use a virtual environment to isolate project dependencies. An environment can be created by running the following commands inside the `code/` directory, or by using other tools like conda:

    ```bash
    python3 -m venv venv
    ```

2.  **Activate the Virtual Environment:**

    ```bash
    . venv/bin/activate
    ```

3.  **Install Requirements:** Install the necessary Python packages listed in the `requirements.txt` file.

    ```bash
    pip install -r requirements.txt
    ```

4.  **Install LSL library:** You can install the LSL library by downloading it from the liblsl releases page assets: https://github.com/sccn/liblsl/releaseswith.  
    Otherwise, if conda was used for creating the environment, the LSL library can be installed by running:
    ```
    conda install -c conda-forge liblsl
    ```

## 3. Code files
The code found in the `code/` directory is organized as follows:
- **`participant_adder.py`**: for adding a new participant to the dataset (creates the dataset if it is not present).
- **`commander.py`**: for sending a LSL trigger to all the softwares listening on LSL network.
- **`recorder_audio_video`**: for recording video from two cameras, their microphones, and from a wireless microphone. Specify the devices indexes in the code.
- **`recorder_ecg_mpu`**: for recording data from ecg and mpu devices as described in the docs. A custom device is required from receiving the data with this program.
- **`safely_merge_dataset`**: for merging different `source/` folders contents. Merge the .tsv files (non motion) data that have the same filename(like for scans.tsv).
- **`annotate_dataset`**: calls the `annotate_dataset` function with a specified path. Annotate the source dataset at that path adding BIDS metadata files.
- **`dataset_utils.py`**: contains a collection of functions and variables referenced by the others python programs in `code/`.
- **`audio_and_video_utilities/`**: contains some utilities used for trubleshooting when recording audio and video, with code for printing the indexes of audio and video devices, and the supported resolution of video devices.
- **`dataset_description_files_templates/`**: contains code that can be used for the creation of a `dataset_description.json` file.


## 4. Getting started
In order to record data is necessary to create the `sourcedata/source` directory since the data will be saved here.  
The easiest way to do that is by adding a new participant using `participant_adder.py` or by doing a recording using the participant "sub-00" from `commander.py`.  
A `dataset_description.json` file in the repository root is required for BIDS compatibility and testing the repository folder on [Bids Validator](https://bids-standard.github.io/bids-validator/), it can be produced using the code in `code/dataset_description_files_templates`. In the root of the repository save a dataset description for a "study" dataset.
