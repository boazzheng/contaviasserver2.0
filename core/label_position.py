import csv
import sys
import os
from shapely.geometry import Point, Polygon

coords = {
"A":(1,196,626,300,445,705,1,407),
"B":(609,337,674,202,713,1,994,1,1143,290,1108,341,865,220,759,288),
"C":(1133,302,1553,18,1719,69,1445,391,1275,366),
"D":(1445,391,1919,417,1919,563,1386,766,1355,563,1333,466,1272,412,1204,334,1275,366),
"E":(311,1080,443,708,518,544,684,747,940,778,1177,737,1369,653,1386,768,1520,714,1569,1080),

}


def convert_coordinates(input_dict):
    output_dict = {}
    
    for key, coords in input_dict.items():
        output_dict[key] = [(coords[i], coords[i+1]) for i in range(0, len(coords), 2)]
    
    return output_dict

def get_position(x, y, positions):
    point = Point(x, y)
    for pos, poly_coords in positions.items():
        polygon = Polygon(poly_coords)
        if polygon.contains(point):
            return pos
    return None

def process_csv(input_file, positions):
    output_file = os.path.splitext(input_file)[0] + '_with_position.csv'

    with open(input_file, mode='r') as infile, open(output_file, mode='w', newline='') as outfile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames + ['starting position', 'ending position']
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)

        writer.writeheader()

        for row in reader:
            start_x = float(row['start x'])
            start_y = float(row['start y'])
            end_x = float(row['end x'])
            end_y = float(row['end y'])

            row['starting position'] = get_position(start_x, start_y, positions)
            row['ending position'] = get_position(end_x, end_y, positions)

            # if (row['starting position'] == '1' and row['ending position'] == '1'):
            #     if start_x < end_x :
            #         row['starting position'] = '4'
            #         row['ending position'] = '1'
            #     else:
            #         row['starting position'] = '1'
            #         row['ending position'] = '4'

            # elif row['starting position'] == '1':
            #     if start_x < 352 / 2:
            #         row['starting position'] = '4'
            #     else:
            #         row['starting position'] = '1'
              
            # elif row['ending position'] == '1':
            #     if end_x < 352 / 2:
            #         row['ending position'] = '1'
            #     else:
            #         row['ending position'] = '4'

            writer.writerow(row)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <input_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    
    # Convert incoming coordinates to the required format
    positions = convert_coordinates(coords)
    
    # Process the CSV file with the converted positions
    process_csv(input_file, positions)
    print(f"Output written to {os.path.splitext(input_file)[0]}_with_position.csv")

# ffmpeg -i DVR-TZ19_01_20240917_170000.mp4 -vframes 1 001_frame.png
# ffmpeg -i in.mp4 -vf select='eq(n\,100)+eq(n\,184)+eq(n\,213)' -vsync 0 frames%d.jpg
# https://www.image-map.net/
# Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force