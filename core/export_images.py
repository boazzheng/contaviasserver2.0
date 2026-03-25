import cv2
import os
import argparse
import json

parser = argparse.ArgumentParser(description='Process output data to generate the best image of vehicle.')
parser.add_argument('-j','--json',help='JSON input of video')
parser.add_argument('-v','--video',help='Video input')
parser.add_argument('-o', '--output', help='Output folder. If folder does not exist, it will be created', default='./output')

args = parser.parse_args()

if not os.path.exists(args.video):
    raise FileNotFoundError(f'Video file "{args.video}" does not exist')

if not os.path.exists(args.json):
    raise FileNotFoundError(f'JSON file "{args.json}" does not exist')





basename = os.path.splitext(os.path.basename(args.video))[0]
output_folder = os.path.join(args.output, basename+"/")

left_folder = os.path.join(output_folder, "1-3/")
right_folder = os.path.join(output_folder, "3-1/")

# Create output folder if it doesn't exist
if not os.path.exists(args.output):
    os.makedirs(args.output)

# Create output folder if it doesn't exist
if not os.path.exists(args.output):
    os.makedirs(args.output)
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

if not os.path.exists(left_folder):
    os.makedirs(left_folder)
if not os.path.exists(right_folder):
    os.makedirs(right_folder)

# Function to check if the object is within 1% margin
def is_within_margin(x, y, width, height, frame_width, frame_height):
    margin_x = frame_width * 0.01
    margin_y = frame_height * 0.01
    
    # Adjust x and y to be the top-left corner
    x = x - (width / 2)
    y = y - (height / 2)
    
    return (margin_x < x < frame_width - width - margin_x) and (margin_y < y < frame_height - height - margin_y) and (x < (frame_width * .5)) # this will only allow for images where the position is the left 50%

cap = cv2.VideoCapture(args.video)
frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

print("Loading JSON Data...")
with open(args.json) as fd:
    json_data = json.load(fd)
    for vehicle in json_data:
        vehicle_id = vehicle['id']
        vehicle_type = vehicle['type']

        if vehicle_type != 'truck' and vehicle_type != 'bus' and vehicle_type != 'reboque':
            continue

        best_pos = None
        largest_area = 0

        first_frame = vehicle['pos'][0]
        last_frame = vehicle['pos'][-1 ]

        for pos in vehicle['pos']:
            frame_num, x, y, width, height = pos
            area = width * height

            # Check if the object is within the margin and if the area is the largest
            if is_within_margin(x, y, width, height, frame_width, frame_height) and area > largest_area:
                largest_area = area
                best_pos = pos

        # Save the best frame for this object if found
        if best_pos is not None:
            direction = 'right' if first_frame[1] < last_frame[1] else 'left'

            frame_num, x_center, y_center, width, height = best_pos

            # Adjust x and y to be the top-left corner
            x = int(x_center - (width / 2))
            y = int(y_center - (height / 2))
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num-1)
            ret, frame = cap.read()
            if ret == True:
                output_path = os.path.join(left_folder if direction == 'left' else right_folder, f'{basename}_frame{frame_num}_{vehicle_type}_{vehicle_id}.png')
                cv2.imwrite(output_path, frame)
                print(f'Best image for {vehicle_type} (ID: {vehicle_id}) saved to {output_path}. Frame {frame_num} of {total_frames}')
            else:
                print(f'Unable to save frame {vehicle_type} (ID: {vehicle_id}). Frame {frame_num} of {total_frames}')
        else:
            print(f'No suitable image found for {vehicle_id} (ID: {vehicle_id})')

cap.release()