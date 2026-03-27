import json
from pathlib import Path
from collections import OrderedDict


# This code was created starting from this official template:
# https://github.com/bids-standard/bids-starter-kit/blob/main/pythonCode/createBIDS_dataset_description_json.py


data = OrderedDict()

# ######################### REQUIRED FIELDS ######################### :
# name of the dataset.
data["Name"] = "Dog Behavior Multimodal Study Dataset"

# The version of the BIDS standard that was used.
data["BIDSVersion"] = "1.10.1"

# RECOMMENDED FIELDS:
# If HED tags are used: The version of the HED schema used to validate HED tags for study.
# May include a single schema or a base schema and one or more library schema.
#data["HEDVersion"] = "" # or array of strings ["", "", ""]

# Used to map a given <dataset-name> from a BIDS URI of the form bids:<dataset-name>:path/within/dataset to a local or remote location.
# The <dataset-name>: "" (an empty string) is a reserved keyword that MUST NOT be a key in DatasetLinks (example: bids::path/within/dataset).

# This field if REQUIRED if BIDS URIs are used.
#data["DatasetLinks"] = ["bids::path/within/dataset"]

# The interpretation of the dataset
# Must be one of: "raw", "derivative", "study".
data["DatasetType"] = "study"

# what license is this dataset distributed under?
# The use of license name abbreviations is suggested for specifying a license.
# A list of common licenses with suggested abbreviations can be found in appendix III.
# data["License"] = "CC-BY-4.0"

# List of individuals who contributed to the creation/curation of the dataset. MUST be omitted if the information is included in a separate CITATION.cff file.
# data["Authors"] = ["", "", ""]


# ######################### OPTIONAL FIELDS ######################### :
# A list of keywords that describe the content or subject matter of the dataset.
data["Keywords"] = ["dog behavior", "animal behavior", "behavioral data", "multimodal dataset"]

# who should be acknowledged in helping to collect the data, should be omitted if the information is included in a separate CITATION.cff file.
#data["Acknowledgements"] = ""

# Instructions how researchers using this dataset should acknowledge the original authors.
# This field can also be used to define a publication that should be cited in publications that use the dataset
# Should be omitted if the information is included in a separate CITATION.cff file under message.
#data["HowToAcknowledge"] = ""

# TODO
# sources of funding (grant numbers), for example "National Institute of Neuroscience Grant F378236MFH1",
#data["Funding"] = ["", "", ""]

# List of ethics committee approvals of the research protocols and/or protocol identifiers.
# data["EthicsApprovals"] = ["ethics approval 1", "ethics approval 2"]

# TODO: update this after the publication of the dataset.
# a list of references to publication that contain information on the dataset, or links.
#data["ReferencesAndLinks"] = ["", "", ""]

# TODO: update this after the publication of the dataset.
# the Document Object Identifier of the dataset (not the corresponding paper).
# data["DatasetDOI"] = "to be updated after publication of the dataset"

# save the dataset_description.json file
from datetime import datetime
output_dir = f"dataset_description_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
Path(output_dir).mkdir(parents=True, exist_ok=True)
dataset_description_filename = Path(output_dir) / "dataset_description.json"

with open(dataset_description_filename, "w") as ff:
    json.dump(data, ff, sort_keys=False, indent=4)

print(f"Dataset description json file created at {dataset_description_filename.resolve()}.\nMove the file to the root directory of the dataset.")