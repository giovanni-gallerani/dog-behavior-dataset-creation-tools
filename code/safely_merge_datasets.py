"""Script to merge multiple datasets like DOG_BEHAVIOR_DATASET into a single one."""

import sys
from pathlib import Path
import shutil
from colorama import init

init()  # enables ANSI colors on Windows


class bcolors:
    COPIED = '\033[92m'
    LINE_MERGED = '\033[95m'
    LINE_SKIPPED = '\033[96m'
    IGNORED = '\033[93m'
    ERROR = '\033[91m'
    ENDC = '\033[0m'


def print_copied(file: str):
    print(f"{bcolors.COPIED}Cpd: {file}{bcolors.ENDC}")


def print_merged(f1: str, line: str):
    print(f"{bcolors.LINE_MERGED}Mln: {f1}, line: {line.strip(chr(10))}{bcolors.ENDC}")


def print_skipped(f1: str, line: str):
    print(f"{bcolors.LINE_SKIPPED}Skp: {f1}, line: {line.strip(chr(10))}{bcolors.ENDC}")


def print_ignored(file: str):
    print(f"{bcolors.IGNORED}Ign: {file}{bcolors.ENDC}")


def print_error(s: str):
    print(f"{bcolors.ERROR}Err: {s}{bcolors.ENDC}")


def recursive_copy_and_merge(input_dir: Path, output_dir: Path, verbose: bool) -> tuple[int, int, int, int, int]:
    """
    Returns numbers of files_copied, files_merged, merges_skipped, files_ignored, errors.
    If verbose == True print each line skipped in the merge of tsv files.
    """
    files_copied = 0
    lines_merged = 0
    lines_skipped = 0
    files_ignored = 0
    errors = 0

    for item in input_dir.iterdir():
        if item.is_dir():
            # take the dirname, create it on the output path if it does not already exist and call recusively
            nested_output_dir = output_dir / item.name
            try:
                nested_output_dir.mkdir(exist_ok=True, parents=True)
                rec_files_copied, rec_lines_merged, rec_merges_skipped, rec_files_ignored, rec_errors = recursive_copy_and_merge(item, nested_output_dir, verbose)
                
                files_copied += rec_files_copied
                lines_merged += rec_lines_merged
                lines_skipped += rec_merges_skipped
                files_ignored += rec_files_ignored
                errors += rec_errors
                
            except Exception as e:
                print_error(f"failed to create directory: {nested_output_dir}. Its contents will be skipped. {e}")
                errors += 1
        else:
            # item is a file
            output_file_path = output_dir / item.name
            if output_file_path.exists() == False:
                # copy the file in the output directory
                try:
                    shutil.copy2(item, output_file_path)
                    print_copied(item)
                    files_copied += 1
                except:
                    print_error(f"failed to copy file {item} into {output_dir}")
                    errors += 1
            else:
                # if the file exist, but is not a tsv file, or it's a motion.tsv file, ignore it
                if not item.name.endswith(".tsv") or item.name.endswith("motion.tsv"):
                    if verbose:
                        print_ignored(f"{input_dir / item.name}")
                    files_ignored += 1
                else:
                    # if it is a tsv file, check if the header is the same, if it is merge the 2 files
                    try:
                        with open(item, "r", newline='', encoding="utf-8") as tsv_input_file, open(output_file_path, "r+", newline='', encoding="utf-8") as tsv_output_file:
                            tsv_input_file_header = tsv_input_file.readline()
                            tsv_output_file_header = tsv_output_file.readline()
                            if tsv_input_file_header == tsv_output_file_header:
                                for line in tsv_input_file:
                                    if line in tsv_output_file:
                                        if verbose:
                                            print_skipped(tsv_input_file.name, line)
                                        lines_skipped += 1
                                    else:
                                        tsv_output_file.write(line)
                                        print_merged(tsv_input_file.name, line)
                                        lines_merged += 1
                            else:
                                print_error(f"impossible to merge {item} and {output_file_path} since they have different headers")
                                errors += 1

                    except Exception as e:
                        print_error(f"merging of {item} and {output_file_path} failed. {e}")
                        errors += 1
    return files_copied, lines_merged, lines_skipped, files_ignored, errors


if __name__ == "__main__":
    # example: python3 merge_datasets.py DOG_BEHAVIOR_DATASET_1 DOG_BEHAVIOR_DATASET_2 DOG_BEHAVIOR_DATASET_3 DOG_BEHAVIOR_DATASET_4

    if len(sys.argv) > 1 and (sys.argv[1] == "--help" or sys.argv[1] == "-h"):
        print("Usage: python merge_dataset.py dataset_path1 dataset_path2 ...")
        print("If given 2 tsv files a line is the same, that line is inserted only one time in the final dataset, and skipped subsequent times")
        print("Add --verbose or -v at the end of the command to print all the files and lines of tsv files ignored because alredy existing in the merged dataset")
        print("This script merges multiple dog behavior datasets into a single dataset. The output dataset is the last one given as input.")
        sys.exit(0)
        
    if sys.argv[-1] == "--verbose" or sys.argv[-1] == "-v":
        verbose = True
        necessary_items = 4
        output_dataset_dir_index = -2
    else:
        verbose = False
        necessary_items = 3
        output_dataset_dir_index = -1
        
    if len(sys.argv) < necessary_items:
        print("Error: At least two dataset paths are required.")
        print("Use --help or -h for usage information.")
        sys.exit(1)

    input_datasets_dirs = [Path(arg) for arg in sys.argv[1:output_dataset_dir_index]]
    output_dataset_dir = Path(sys.argv[output_dataset_dir_index])
    
    # validate input datasets paths
    for dir in input_datasets_dirs:
        if dir.is_dir() == False:
            print_error(f"Dataset path {dir} is not an existing directory.")
            sys.exit(1)
        if input_datasets_dirs.count(dir) > 1:
            reply = None
            try:
                while reply not in ["y", "n"]:
                    reply = input(f"Some datasets are listed multiple times as input, probably this is not intended. Continue? (y/n): ")
            except KeyboardInterrupt:
                print("")
                sys.exit(0)
            if reply == "y":
                break
            if reply == "n":
                sys.exit(0)
            

    # create output dataset directory if it does not already exists
    try:
        output_dataset_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating output dataset directory: {e}")
        sys.exit(1)
    
    print("--- MERGE START ---")
    # for each dataset given as input, copy its content and merge tsv files with the same name and position
    files_copied = 0
    lines_merged = 0
    lines_skipped = 0
    files_ignored = 0
    errors = 0
    
    for dir in input_datasets_dirs:
        (
            instance_file_copied, 
            instance_lines_merged, 
            instance_lines_skipped, 
            instance_files_ignored,
            instance_errors
        ) = recursive_copy_and_merge(dir, output_dataset_dir, verbose)
        files_copied += instance_file_copied
        lines_merged += instance_lines_merged
        lines_skipped += instance_lines_skipped
        files_ignored += instance_files_ignored
        errors += instance_errors
    print("--- MERGE END ---")

    print("")
    print(f"Input datasets: {[str(dir) for dir in input_datasets_dirs]}")
    print(f"Output dataset: {str(output_dataset_dir)}")
    print(f"Datasets merge completed:")
    print(f"{bcolors.COPIED}{files_copied} files copied{bcolors.ENDC}")
    print(f"{bcolors.LINE_MERGED}{lines_merged} tsv lines merged{bcolors.ENDC}")
    print(f"{bcolors.IGNORED}{files_ignored} files ignored{bcolors.ENDC}")
    print(f"{bcolors.LINE_SKIPPED}{lines_skipped} tsv lines skipped{bcolors.ENDC}")
    print(f"{bcolors.ERROR}{errors} errors{bcolors.ENDC}")
