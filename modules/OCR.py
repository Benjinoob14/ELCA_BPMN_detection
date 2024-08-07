
import os
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures
from azure.core.credentials import AzureKeyCredential
import time
import numpy as np
import networkx as nx
from modules.utils import class_dict, proportion_inside
import json
from modules.utils import rescale_boxes as rescale 
from modules.utils import is_vertical


#VISION_KEY = os.getenv("VISION_KEY")
#VISION_ENDPOINT = os.getenv("VISION_ENDPOINT")

#If local execution
with open("VISION_KEY.json", "r") as json_file:
    json_data = json.load(json_file)
    
VISION_KEY = json_data["VISION_KEY"]
VISION_ENDPOINT = json_data["VISION_ENDPOINT"]


def sample_ocr_image_file(image_data):
    # Set the values of your computer vision endpoint and computer vision key
    # as environment variables:
    try:
        endpoint = VISION_ENDPOINT
        key = VISION_KEY
    except KeyError:
        print("Missing environment variable 'VISION_ENDPOINT' or 'VISION_KEY'")
        print("Set them before running this sample.")
        exit()

    # Create an Image Analysis client
    client = ImageAnalysisClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )

    # Extract text (OCR) from an image stream. This will be a synchronously (blocking) call.
    result = client.analyze(
        image_data=image_data,
        visual_features=[VisualFeatures.READ]
    )
                
    return result


def text_prediction(image):
    #transform the image into a byte array
    image.save('temp.jpg')
    with open('temp.jpg', 'rb') as f:
        image_data = f.read()
    ocr_result = sample_ocr_image_file(image_data)
    #delete the temporary image
    os.remove('temp.jpg')
    return ocr_result

def filter_text(ocr_result, threshold=0.5):
    words_to_cancel = {"+",".",",","#","@","!","?","(",")","[","]","{","}","<",">","/","\\","|","-","_","=","&","^","%","$","£","€","¥","¢","¤","§","©","®","™","°","±","×","÷","¶","∆","∏","∑","∞","√","∫","≈","≠","≤","≥","≡","∼"}
    # Add every other one-letter word to the list of words to cancel, except 'I' and 'a'
    for letter in "bcdefghjklmnopqrstuvwxyz1234567890":  # All lowercase letters except 'a'
        words_to_cancel.add(letter)
        words_to_cancel.add("i")
        words_to_cancel.add(letter.upper())  # Add the uppercase version as well
    characters_to_cancel = {"+", "<", ">"}  # Characters to cancel
    
    list_of_lines = []

    for block in ocr_result['readResult']['blocks']:
        for line in block['lines']:
            line_text = []
            x_min, y_min = float('inf'), float('inf')
            x_max, y_max = float('-inf'), float('-inf')
            for word in line['words']:
                if word['text'] in words_to_cancel or any(disallowed_char in word['text'] for disallowed_char in characters_to_cancel):
                    continue
                if word['confidence'] > threshold:
                    if word['text']:
                        line_text.append(word['text'])
                        x = [point['x'] for point in word['boundingPolygon']]
                        y = [point['y'] for point in word['boundingPolygon']]
                        x_min = min(x_min, min(x))
                        y_min = min(y_min, min(y))
                        x_max = max(x_max, max(x))
                        y_max = max(y_max, max(y))
            if line_text:  # If there are valid words in the line
                list_of_lines.append({
                    'text': ' '.join(line_text),
                    'boundingBox': [x_min,y_min,x_max,y_max]
                })
    
    list_text = []
    list_bbox = []
    for i in range(len(list_of_lines)):
        list_text.append(list_of_lines[i]['text'])
    for i in range(len(list_of_lines)):
        list_bbox.append(list_of_lines[i]['boundingBox'])

    list_of_lines = [list_bbox, list_text]

    return list_of_lines




def get_box_points(box):
    """Returns all critical points of a box: corners and midpoints of edges."""
    xmin, ymin, xmax, ymax = box
    return np.array([
        [xmin, ymin],  # Bottom-left corner
        [xmax, ymin],  # Bottom-right corner
        [xmin, ymax],  # Top-left corner
        [xmax, ymax],  # Top-right corner
        [(xmin + xmax) / 2, ymin],  # Midpoint of bottom edge
        [(xmin + xmax) / 2, ymax],  # Midpoint of top edge
        [xmin, (ymin + ymax) / 2],  # Midpoint of left edge
        [xmax, (ymin + ymax) / 2]   # Midpoint of right edge
    ])

def min_distance_between_boxes(box1, box2):
    """Computes the minimum distance between two boxes considering all critical points."""
    points1 = get_box_points(box1)
    points2 = get_box_points(box2)
    
    min_dist = float('inf')
    for point1 in points1:
        for point2 in points2:
            dist = np.linalg.norm(point1 - point2)
            if dist < min_dist:
                min_dist = dist
    return min_dist


def is_inside(box1, box2):
    """Check if the center of box1 is inside box2."""
    x_center = (box1[0] + box1[2]) / 2
    y_center = (box1[1] + box1[3]) / 2
    return box2[0] <= x_center <= box2[2] and box2[1] <= y_center <= box2[3]

def are_close(box1, box2, threshold=50):
    """Determines if boxes are close based on their corners and center points."""
    corners1 = np.array([
        [box1[0], box1[1]], [box1[0], box1[3]], [box1[2], box1[1]], [box1[2], box1[3]],
        [(box1[0]+box1[2])/2, box1[1]], [(box1[0]+box1[2])/2, box1[3]],
        [box1[0], (box1[1]+box1[3])/2], [box1[2], (box1[1]+box1[3])/2]
    ])
    corners2 = np.array([
        [box2[0], box2[1]], [box2[0], box2[3]], [box2[2], box2[1]], [box2[2], box2[3]],
        [(box2[0]+box2[2])/2, box2[1]], [(box2[0]+box2[2])/2, box2[3]],
        [box2[0], (box2[1]+box2[3])/2], [box2[2], (box2[1]+box2[3])/2]
    ])
    for c1 in corners1:
        for c2 in corners2:
            if np.linalg.norm(c1 - c2) < threshold:
                return True
    return False

def find_closest_box(text_box, all_boxes, labels, threshold, iou_threshold=0.5):
    """Find the closest box to the given text box within a specified threshold."""
    min_distance = float('inf')
    closest_index = None

    #check if the text is inside a sequenceFlow
    for j in range(len(all_boxes)):
        if proportion_inside(text_box, all_boxes[j])>iou_threshold and labels[j] == list(class_dict.values()).index('sequenceFlow'):
            return j
    
    for i, box in enumerate(all_boxes):
        # Compute the center of both boxes
        center_text = np.array([(text_box[0] + text_box[2]) / 2, (text_box[1] + text_box[3]) / 2])
        center_box = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
        
        # Calculate Euclidean distance between centers
        distance = np.linalg.norm(center_text - center_box)
        
        # Update closest box if this box is nearer
        if distance < min_distance:
            min_distance = distance
            closest_index = i

    # Check if the closest box found is within the acceptable threshold
    if min_distance < threshold:
        return closest_index
    
    return None



def group_texts(task_boxes, text_boxes, texts, min_dist=50, iou_threshold=0.8, percentage_thresh=0.8):
    """Maps text boxes to task boxes and groups texts within each task based on proximity."""
    G = nx.Graph()

    # Map each text box to the nearest task box
    task_to_texts = {i: [] for i in range(len(task_boxes))}
    information_texts = []  # texts not inside any task box
    text_to_task_mapped = [False] * len(text_boxes)

    for idx, text_box in enumerate(text_boxes):
        mapped = False
        for jdx, task_box in enumerate(task_boxes):
            if proportion_inside(text_box, task_box)>iou_threshold:
                task_to_texts[jdx].append(idx)
                text_to_task_mapped[idx] = True
                mapped = True
                break
        if not mapped:
            information_texts.append(idx)

    all_grouped_texts = []
    sentence_boxes = []  # Store the bounding box for each sentence

    # Process texts for each task
    for task_texts in task_to_texts.values():
        G.clear()
        for i in task_texts:
            G.add_node(i)
            for j in task_texts:
                if i != j and are_close(text_boxes[i], text_boxes[j]) and not is_vertical(text_boxes[i]) and not is_vertical(text_boxes[j]):
                    G.add_edge(i, j)

        groups = list(nx.connected_components(G))
        for group in groups:
            group = list(group)
            lines = {}
            for idx in group:
                y_center = (text_boxes[idx][1] + text_boxes[idx][3]) / 2
                found_line = False
                for line in lines:
                    if abs(y_center - line) < (text_boxes[idx][3] - text_boxes[idx][1]) / 2:
                        lines[line].append(idx)
                        found_line = True
                        break
                if not found_line:
                    lines[y_center] = [idx]

            sorted_lines = sorted(lines.keys())
            grouped_texts = []
            min_x = min_y = float('inf')
            max_x = max_y = -float('inf')

            for line in sorted_lines:
                sorted_indices = sorted(lines[line], key=lambda idx: text_boxes[idx][0])
                line_text = ' '.join(texts[idx] for idx in sorted_indices)
                grouped_texts.append(line_text)

                for idx in sorted_indices:
                    box = text_boxes[idx]
                    min_x = min(min_x-5, box[0]-5)
                    min_y = min(min_y-5, box[1]-5)
                    max_x = max(max_x+5, box[2]+5)
                    max_y = max(max_y+5, box[3]+5)

            all_grouped_texts.append(' '.join(grouped_texts))
            sentence_boxes.append([min_x, min_y, max_x, max_y])

    # Group information texts
    G.clear()
    info_sentence_boxes = []

    for i in information_texts:
        G.add_node(i)
        for j in information_texts:
            if i != j and are_close(text_boxes[i], text_boxes[j], percentage_thresh * min_dist) and not is_vertical(text_boxes[i]) and not is_vertical(text_boxes[j]):
                G.add_edge(i, j)

    info_groups = list(nx.connected_components(G))
    information_grouped_texts = []
    for group in info_groups:
        group = list(group)
        lines = {}
        for idx in group:
            y_center = (text_boxes[idx][1] + text_boxes[idx][3]) / 2
            found_line = False
            for line in lines:
                if abs(y_center - line) < (text_boxes[idx][3] - text_boxes[idx][1]) / 2:
                    lines[line].append(idx)
                    found_line = True
                    break
            if not found_line:
                lines[y_center] = [idx]

        sorted_lines = sorted(lines.keys())
        grouped_texts = []
        min_x = min_y = float('inf')
        max_x = max_y = -float('inf')

        for line in sorted_lines:
            sorted_indices = sorted(lines[line], key=lambda idx: text_boxes[idx][0])
            line_text = ' '.join(texts[idx] for idx in sorted_indices)
            grouped_texts.append(line_text)

            for idx in sorted_indices:
                box = text_boxes[idx]
                min_x = min(min_x, box[0])
                min_y = min(min_y, box[1])
                max_x = max(max_x, box[2])
                max_y = max(max_y, box[3])

        information_grouped_texts.append(' '.join(grouped_texts))
        info_sentence_boxes.append([min_x, min_y, max_x, max_y])

    return all_grouped_texts, sentence_boxes, information_grouped_texts, info_sentence_boxes


def mapping_text(full_pred, text_pred, print_sentences=False,percentage_thresh=0.6,scale=1.0, iou_threshold=0.5):

    ########### REFAIRE CETTE FONCTION ###########
    #refaire la fonction pour qu'elle prenne en premier les elements qui sont dans les task et ensuite prendre un seuil de distance pour les autres elements
    #ou sinon faire la distance entre les elements et non pas seulement les tasks


     # Example usage
    boxes = rescale(scale, full_pred['boxes'])

    min_dist = 200
    labels = full_pred['labels']
    avoid = [list(class_dict.values()).index('pool'), list(class_dict.values()).index('lane'), list(class_dict.values()).index('sequenceFlow'), list(class_dict.values()).index('messageFlow'), list(class_dict.values()).index('dataAssociation')]
    for i in range(len(boxes)):
            box1 = boxes[i]
            if labels[i] in avoid:
                continue
            for j in range(i + 1, len(boxes)):
                    box2 = boxes[j]
                    if labels[j] in avoid:
                        continue
                    dist = min_distance_between_boxes(box1, box2)
                    min_dist = min(min_dist, dist)

    #print("Minimum distance between boxes:", min_dist)

    text_pred[0] = rescale(scale, text_pred[0])
    task_boxes = [box for i, box in enumerate(boxes) if full_pred['labels'][i] == list(class_dict.values()).index('task')]
    grouped_sentences, sentence_bounding_boxes, info_texts, info_boxes = group_texts(task_boxes, text_pred[0], text_pred[1], min_dist=min_dist)
    BPMN_id = set(full_pred['BPMN_id'])  # This ensures uniqueness of task names
    text_mapping = {id: '' for id in BPMN_id}
 

    if print_sentences:
        for sentence, box in zip(grouped_sentences, sentence_bounding_boxes):
            print("Task-related Text:", sentence)
            print("Bounding Box:", box)
        print("Information Texts:", info_texts)
        print("Information Bounding Boxes:", info_boxes)

    # Map the grouped sentences to the corresponding task
    for i in range(len(sentence_bounding_boxes)):
        for j in range(len(boxes)):
            if proportion_inside(sentence_bounding_boxes[i], boxes[j])>iou_threshold and full_pred['labels'][j] == list(class_dict.values()).index('task'):
                text_mapping[full_pred['BPMN_id'][j]]=grouped_sentences[i]

    # Map the grouped sentences to the corresponding pool
    for i in range(len(info_boxes)):
        if is_vertical(info_boxes[i]):
            for j in range(len(boxes)):
                if proportion_inside(info_boxes[i], boxes[j])>0 and full_pred['labels'][j] == list(class_dict.values()).index('pool'):
                    print("Text:", info_texts[i], "associate with ", full_pred['BPMN_id'][j])
                    bpmn_id = full_pred['BPMN_id'][j]
                    # Append new text or create new entry if not existing
                    if bpmn_id in text_mapping:
                        text_mapping[bpmn_id] += " " + info_texts[i]  # Append text with a space in between
                    else:
                        text_mapping[bpmn_id] = info_texts[i]
                    info_texts[i] = ''  # Clear the text to avoid re-use

    # Map the grouped sentences to the corresponding object
    for i in range(len(info_boxes)):
        if is_vertical(info_boxes[i]):
            continue  # Skip if the text is vertical
        for j in range(len(boxes)):
            if info_texts[i] == '':
                continue  # Skip if there's no text        
            if (proportion_inside(info_boxes[i], boxes[j])>0 or are_close(info_boxes[i], boxes[j], threshold=percentage_thresh*min_dist)) and (full_pred['labels'][j] == list(class_dict.values()).index('event') 
                                                                             or full_pred['labels'][j] == list(class_dict.values()).index('messageEvent') 
                                                                             or full_pred['labels'][j] == list(class_dict.values()).index('timerEvent')
                                                                             or full_pred['labels'][j] == list(class_dict.values()).index('dataObject')) :
                bpmn_id = full_pred['BPMN_id'][j]
                # Append new text or create new entry if not existing
                if bpmn_id in text_mapping:
                    text_mapping[bpmn_id] += " " + info_texts[i]  # Append text with a space in between
                else:
                    text_mapping[bpmn_id] = info_texts[i]
                info_texts[i] = ''  # Clear the text to avoid re-use

    # Map the grouped sentences to the corresponding flow
    for i in range(len(info_boxes)):
        if info_texts[i] == '' or is_vertical(info_boxes[i]):
            continue  # Skip if there's no text
        # Find the closest box within the defined threshold
        closest_index = find_closest_box(info_boxes[i], boxes, full_pred['labels'], threshold=4*min_dist) 
        if closest_index is not None and (full_pred['labels'][closest_index] == list(class_dict.values()).index('sequenceFlow') or full_pred['labels'][closest_index] == list(class_dict.values()).index('messageFlow')):
            bpmn_id = full_pred['BPMN_id'][closest_index]
            # Append new text or create new entry if not existing
            if bpmn_id in text_mapping:
                text_mapping[bpmn_id] += " " + info_texts[i]  # Append text with a space in between
            else:
                text_mapping[bpmn_id] = info_texts[i]
            info_texts[i] = ''  # Clear the text to avoid re-use

    if print_sentences:
        print("Text Mapping:", text_mapping)
        print("Information Texts left:", info_texts)
                    
    return text_mapping