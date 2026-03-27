import cv2

def detect_video_devices(max_tested=100):
    """max_tested is necessary since sometimes there are empty indexes between diffenet devices"""
    available = []
    for i in range(max_tested):
        cap = cv2.VideoCapture(i)    
        if cap.isOpened():
            available.append(str(i))
            cap.release()
    return available

if __name__ == "__main__":
    print(f"Video device detected: {detect_video_devices()}")