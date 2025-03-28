import time
import pandas as pd
import numpy as np
import glob, sys, serial, os
from pynput import keyboard
from brainflow.board_shim import BoardShim, BrainFlowInputParams
from threading import Thread, Event
from queue import Queue
from serial import Serial

# Ask user for run number and subject ID
subject_id = input("Enter subject ID: ")
run = int(input("Enter run number: "))

# Experiment Parameters
lsl_out = False
save_dir = 'data/misc/'  # Directory to save data
save_file_aux = save_dir + f'aux_-{subject_id}_run-{run}.npy'
save_file_eeg = save_dir + f'eeg_-{subject_id}_run-{run}.csv'
save_file_labels = save_dir + f'labels_subject-{subject_id}_run-{run}.csv'

# Initialize BrainFlow with OpenBCI Connection
CYTON_BOARD_ID = 0
BAUD_RATE = 115200
ANALOGUE_MODE = '/2'

def find_openbci_port():
    """Finds the port to which the Cyton Dongle is connected."""
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        ports = glob.glob('/dev/ttyUSB*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/cu.usbserial*')
    else:
        raise EnvironmentError('Error finding ports on your OS')
    
    for port in ports:
        try:
            s = Serial(port=port, baudrate=BAUD_RATE, timeout=None)
            s.write(b'v')
            time.sleep(2)
            if s.inWaiting():
                line = s.read(s.inWaiting()).decode('utf-8', errors='replace')
                if 'OpenBCI' in line:
                    s.close()
                    return port
            s.close()
        except (OSError, serial.SerialException):
            pass
    raise OSError('Cannot find OpenBCI port.')

print(BoardShim.get_board_descr(CYTON_BOARD_ID))
params = BrainFlowInputParams()
params.serial_port = 'COM6'
board = BoardShim(CYTON_BOARD_ID, params)
board.prepare_session()
board.config_board(ANALOGUE_MODE)
board.start_stream(45000)

# Data Storage
timestamps = []
labels = []
eeg_data = []
queue_in = Queue()
stop_event = Event()

def get_data(queue_in):
    while not stop_event.is_set():
        data_in = board.get_board_data()
        timestamp_in = data_in[board.get_timestamp_channel(CYTON_BOARD_ID)]
        eeg_in = data_in[board.get_eeg_channels(CYTON_BOARD_ID)]
        aux_in = data_in[board.get_analog_channels(CYTON_BOARD_ID)]
        if len(timestamp_in) > 0:
            queue_in.put((eeg_in, aux_in, timestamp_in))
            for i in range(len(timestamp_in)):
                eeg_data.append([timestamp_in[i]] + list(eeg_in[:, i]))
        time.sleep(0.1)

def on_press(key):
    global timestamps, labels
    try:
        if key.char == '1':
            label = "Lost Focus"
        elif key.char == '2':
            label = "Focused Again"
        elif key.char == '3':
            label = "Lecture Started"
        elif key.char == '4':
            label = "Lecture Paused"
        else:
            return
        
        timestamp = time.time()
        timestamps.append(timestamp)
        labels.append(label)
        print(f"[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] {label}")
    except AttributeError:
        pass

def main():
    print("Press 1 for 'Lost Focus', 2 for 'Focused Again', 3 for 'Lecture Started', 4 for 'Lecture Paused'")
    
    cyton_thread = Thread(target=get_data, args=(queue_in,))
    cyton_thread.daemon = True
    cyton_thread.start()
    
    with keyboard.Listener(on_press=on_press) as listener:
        try:
            while True:
                time.sleep(0.1)  # Keep the program running
        except KeyboardInterrupt:
            print("Stopping recording...")
            stop_event.set()
            listener.stop()
            board.stop_stream()
            board.release_session()
            
            # Save attention tracking data
            df = pd.DataFrame({"Timestamp": timestamps, "Label": labels})
            df.to_csv(save_file_labels, index=False)
            print(f"Labels saved to {save_file_labels}")
            
            # Save EEG data to CSV
            eeg_df = pd.DataFrame(eeg_data, columns=["Timestamp"] + [f"EEG_{i+1}" for i in range(len(eeg_data[0])-1)])
            eeg_df.to_csv(save_file_eeg, index=False)
            print(f"EEG data saved to {save_file_eeg}")
            
            # Save EEG auxiliary data
            os.makedirs(save_dir, exist_ok=True)
            aux_data = np.hstack([queue_in.get()[1] for _ in range(queue_in.qsize())])
            np.save(save_file_aux, aux_data)
            print(f"Auxiliary data saved to {save_file_aux}")

if __name__ == "__main__":
    main()
