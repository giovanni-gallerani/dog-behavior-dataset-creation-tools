import cv2
import time
import pandas as pd

VIDEO_DEVICE_INDEX = 0

def set_resolution(cap: cv2.VideoCapture, x, y):
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(x))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(y))

def get_resolution(cap: cv2.VideoCapture):
    return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

def get_supported_res(cap: cv2.VideoCapture, res_list: list):
    supported_res = []
    for res_tuple in res_list:
        print("-------------")
        print(f"Trying: {res_tuple}")

        prev_res = get_resolution(cap)
        print(f"Before was: {prev_res}")

        # update res
        set_resolution(cap, res_tuple[0], res_tuple[1])
        time.sleep(0.1)

        updated_res = get_resolution(cap)
        print(f"Now is: {updated_res}")
        
        print("-------------")
        # if the resolution has changed it means that it's supported
        if updated_res != prev_res:
            supported_res.append(updated_res)
        
    return supported_res
    

if __name__ == "__main__":
    # Specify the path to ODS file containing all the used resolutions
    # from https://en.wikipedia.org/wiki/List_of_common_display_resolutions
    file_path = 'resolutions.ods'

    # Read the ODS file
    # pandas.read_excel can handle ODS files if odfpy is installed
    df = pd.read_excel(file_path, engine='odf', usecols=['W', 'H']) 

    # Create a list of tuples with the possible resolutions
    res_list = []
    for index, row in df.iterrows():
        res_list.append((int(row['W']), int(row['H'])))
    
    cap = cv2.VideoCapture(VIDEO_DEVICE_INDEX)
    #cap = cv2.VideoCapture(VIDEO_DEVICE_INDEX, cv2.CAP_DSHOW) # this is the magic for windows apparently!
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 10)

    print(f"Frame default resolution: {get_resolution(cap)}")

    print(get_supported_res(cap, res_list))

    exit(0)