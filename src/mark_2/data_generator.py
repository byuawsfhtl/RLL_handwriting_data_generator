import json
import random
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from fontTools.ttLib import TTFont
import yaml
import albumentations as A

# Current:
# TODO: fix some logic errors in the get character dimensions. 

# Future:
# TODO: We could create a dictionary that maps the words in the dict to the true dimensions for the words and append those as we go.
# TODO: See if we can find a way to guarantee that something is drawn by the methods in fontLetterPlotDictionaryInstantiator.
# TODO: Fix the logical errors in get_font_letter_plot_dictionary.
# TODO: Class that draws underlines on images in a deterministic manner, for image that have multiple lines of text. Underline shouldn't always have a slope of zero.
# TODO: Fix the way that height, width and start coordinates for characters for a given font and font size are determined. 
# TODO: Rather than dynamically compute all the letter sizes from the get go, do this for each word rendered during runtime. Cut the up front time.
# TODO: Rather than compute the length of a word each time it is to be rendered even if it's been rendered before, store this information dynamically, unless the vocab is very large. Define what this means. 
# TODO: make sure that the array assignment for underline color in the draw_underline function in the draw word on image class is working.

class CustomError(Exception):
    """Custom exception for specific error handling."""
    def __init__(self, message):
        """
        Initialize the custom error.
        
        Args:
            message (str): Description of the error.
        """
        super().__init__(message)

    def __str__(self):
        """
        Return a string representation of the error.
        """
        return self.args[0]

class vocabManager():
    """
    This class manages a vocabulary of text.

    Attributes:
        vocabulary (list): A list of strings.
        index (int): The index of the next element to be returned from the vocabulary if returning text in order.
        vocab_length (int): This is the length of the vocabulary.
    """
    def __init__(self, path_to_vocabulary: str):
        self.vocabulary = self.load_vocabularly(path_to_vocabulary)
        self.index = 0
        self.vocab_length = len(self.vocabulary)

    def load_vocabularly(self, path_to_vocabulary: str) -> list[str]:
        """
        This function loads a json file that expects the json object to have a key named \"vocabulary\" that maps to a list of text. It gets said list of text and returns it.

        Args: 
            path_to_vocabulary (str): A file path to a json file.
            vocab_key (str): A string object that is a key in the json object. 
        """
        with open(path_to_vocabulary, 'r') as json_file_in:
            vocabulary = json.load(json_file_in)["vocabulary"]
        return vocabulary

    def get_random_text_from_vocab(self) -> str:
        """
        Randomly samples an element from the vocabulary.
        """
        return random.choice(self.vocabulary)

    def get_next_text_from_vocab(self) -> str:
        """
        Returns the next element from the vocabulary based on the current index. Each time this method is called the index is incremented. 
        If the incremented index is equal to the length of the vocabulary, the index will be reset to 0 and the subsequent time this method is called the first element in the list will 
        be returned. 
        """
        index = self.index
        self.index += 1
        if self.index == self.vocab_length:
            self.index = 0
        return self.vocabulary[index]

    def get_text(self, get_text_randomly: bool) -> str:
        if get_text_randomly:
            return self.get_random_text_from_vocab()
        else:
            return self.get_next_text_from_vocab()

class fontObjectManager():
    """
    This class manages the different font objects and the frequency with which they should be seen. 
    """

    def __init__(self, fonts_and_weights_path: str, font_size_lower_bound: int, font_size_upper_bound: int):
        fonts_and_weights_dict = self.load_fonts_and_weights_dict(fonts_and_weights_path)
        self.smallest_weight = self.get_smallest_font_weight(fonts_and_weights_dict)
        self.font_dictionaries = self.create_list_of_fonts_to_sample_from(fonts_and_weights_dict, font_size_lower_bound, font_size_upper_bound)
        self.font_size_lower_bound = font_size_lower_bound
        self.font_size_upper_bound = font_size_upper_bound

    def load_fonts_and_weights_dict(self, fonts_and_weights_path: str) -> dict:
        with open(fonts_and_weights_path, 'r') as json_in:
            return json.load(json_in)

    def get_smallest_font_weight(self, fonts_and_weights) -> float:
        """
        The fonts and weights dict contains paths to different font objects and the how often that font object should be seen in proportion to the other font objects. 
        The font weights should sum to approximately one. This code finds the smallest weight across all fonts. 

        Args:
            font_and_weights (dict): A dictionary that maps font_paths to a float value that represents the weight of that font. 
        """
        return min(list(fonts_and_weights.values())) # TODO: Make sure this works.

    def create_list_of_fonts_to_sample_from(self, fonts_and_weights, font_size_lower_bound, font_size_upper_bound) -> list[dict]:
        """
        This function creates a list of dictionaries where each dictionary contains ImageFont objects for each font size in our range font_size_lower_bound to font_size_upper_bound.
        Some of the elements of the list are the same dictionaries as other elements in the list. This is how the weighting of different fonts is determined. Since the objects are referenced, there
        is little space taken up. 

        Args:
            font_and_weights (dict): A dictionary that maps font_paths to a float value that represents the weight of that font. 
            font_size_lower_bound (int): An integer value that represents the smallest value we allow a font to take.
            font_size_upper_bound (int): An integer value that represents the largest value we allow a font to take.
        """
        list_of_font_dictionaries = []
        for font_file_path, weight in fonts_and_weights.items():
            font_dict = {}
            for font_size in range(font_size_lower_bound, (font_size_upper_bound+1)):
                font_dict[font_size] = ImageFont.truetype(font_file_path, font_size)
            number_of_times_to_add_font = round(weight/self.smallest_weight)
            for _ in range(number_of_times_to_add_font):
                list_of_font_dictionaries.append(font_dict)
        return list_of_font_dictionaries


class fontObjectManagerGivenCharacters(fontObjectManager):
    """
    This class determines which fonts support the characters found in each word in our vocabularly.
    """
    def __init__(self, vocabulary: list, fonts_and_weights_path: str, font_size_lower_bound: int, font_size_upper_bound: int):
        super().__init__(fonts_and_weights_path, font_size_lower_bound, font_size_upper_bound)
        self.character_to_font_indicies = self.determine_fonts_for_characters(vocabulary)
        self.ensure_fonts_support_characters(vocabulary)

    def determine_fonts_for_characters(self, vocabulary: list) -> dict:
        """
        This function detmermines which fonts that have a UTF-encoding character map that supports given characters. 
        This information is then used to map each character in the vocabulary to a list of indicies that correspond to fonts that support that character. 

        Args:
            vocabulary (list): The words that we want to be generated by the data generator.
        """
        TTFonts_and_font_dicts = {} # Generate a list of ttfont objects to check the character map and a font_dict
        last_font_path = None
        for index, font_dict in enumerate(self.font_dictionaries):
            font_path = font_dict[self.font_size_lower_bound].path
            if last_font_path:
                if last_font_path == font_path:
                    TTFonts_and_font_dicts[index] = TTFonts_and_font_dicts[index-1]
                else:
                    TTFonts_and_font_dicts[index] = (font_dict, TTFont(font_path))
                    last_font_path = font_path
            else:
                TTFonts_and_font_dicts[index] = (font_dict, TTFont(font_path))
                last_font_path = font_path
        char_dict = {} # A dictionary to keep track of which fonts can be used for what character. 
        self.determine_correct_fonts_for_characters("c", char_dict, TTFonts_and_font_dicts)
        for text in vocabulary: # Iterate through the vocabulary to find what fonts will be appropriate for the text. 
            if text == "" or text == "dash_in_image_field": # This will render no text on the image so any font will work for this. 
                char_dict[text] = set()
                for index in TTFonts_and_font_dicts:
                    char_dict[text].add(index)
            else:
                reduced_text = self.get_reduced_text(text) # Words an sentences often have many of the same characters in them. Get the unique characters in ascending order.
                for character in reduced_text: 
                    if character not in char_dict:
                        self.determine_correct_fonts_for_characters(character, char_dict, TTFonts_and_font_dicts) 
        return char_dict
    
    def determine_correct_fonts_for_characters(self, character: str, char_dict: dict, TTFonts_and_font_dicts: dict):
        char_dict[character] = set() # We will want to store all of the references for fonts that contain a rendering of that character. 
        char_code = ord(character) # Get the unicode encoding of the character.
        set_of_capable_fonts = set() # Since our fonts are weighted, our list of fonts we sample from may have duplicate references to the same font. As such, if we want to add this font more than once we have no need to check if the character is supported by the font multiple times.
        set_of_incapable_fonts = set() # Ditto to the above comment but we don't want to add these fonts. 
        for index in TTFonts_and_font_dicts.keys(): # For every font in our list of fonts. 
            font_path = TTFonts_and_font_dicts[index][0][self.font_size_lower_bound].path # Get the font path for the given font object
            ttfont = TTFonts_and_font_dicts[index][1]
            if font_path in set_of_capable_fonts: # If this font has already been checked and we know it supports the character then add it to our dictionary. 
                char_dict[character].add(index) # Add the given index to the font to our char_dict for the given character that has the supported font. 
            elif font_path in set_of_incapable_fonts: # Do nothing, we don't want that font. 
                continue
            else:
                cmap = ttfont.get("cmap") # Get the cmap tables from the font file. 
                if not cmap:
                    set_of_incapable_fonts.add(font_path) # If the font file doesn't have one then the font is unusable.
                else:
                    found_capable_font = False 
                    for table in cmap.tables: # Look for the table that corresponds to UTF
                        platform_id = table.platformID
                        encoding_id = table.platEncID
                        if platform_id == 3 and encoding_id == 1:
                            if char_code in table.cmap:
                                char_dict[character].add(index)
                                found_capable_font = True
                                break
                    if found_capable_font:
                        set_of_capable_fonts.add(font_path)
                    else:
                        set_of_incapable_fonts.add(font_path)

    def get_reduced_text(self, text: str) -> str:
        """
        This function takes a given word and returns the unique characters found in that word in ascending order.

        Args:
            text (str): This is a word from the vocabulary.
        """
        if text == "":
            return text
        elif text == "dash_in_word_image":
            return text
        else:
            temp_list = []
            last_character = None
            for character in sorted(text):
                if last_character:
                    if last_character != character:
                        temp_list.append(character)
                        last_character = character
                else:
                    temp_list.append(character)
                    last_character = character
            return ''.join(temp_list)
        
    def ensure_fonts_support_characters(self, vocabulary: list):
        # Get all of the unique characters from the vocabulary
        set_of_characters = set()
        set_of_characters.add("c")
        for word in vocabulary:
            if word != "dash_in_image_field":
                for character in word:
                    set_of_characters.add(character)
        # Check that each character has some fonts that support it. Otherwise raise error.
        unsupported_characters = set()
        for character in set_of_characters:
            if len(self.character_to_font_indicies[character]) == 0:
                unsupported_characters.add(character)
        if len(unsupported_characters) > 0:
            output_string = ", ".join([ord(character) for character in unsupported_characters])
            raise CustomError(f"You have the following characters (represented as character codes) in your vocabulary that don't have fonts that support them: {output_string}")
        """# Check that a font exists to support all of the characters in the vocabulary.
        all_text_with_c = "".join([character for character in set_of_characters])
        list_of_potential_fonts = list(set.intersection(*[self.character_to_font_indicies[character] for character in all_text_with_c]))
        if len(list_of_potential_fonts) == 0:
            raise CustomError("There is not a single font you've selected that supports every character in the vocabulary. It is requisite that there is one font that has all of the characters in the font glyph.")
"""
class fontLetterPlotDictionaryInstantiator():
    """
    This class create a dictionary object that determines the height, width and start coordinates for characters that can be drawn on an image given a font type and a font size. 
    """
    @staticmethod
    def get_font_letter_plot_dictionary(font_object_manager_given_characters: fontObjectManagerGivenCharacters, vocabulary: list) -> dict:
        """
        This is the main function of the class. It returns a dictionary object that maps the paths to font objects to font sizes, and maps font sizes to a character, and maps the character to height, width and start coordinates for that character. 
        """
        font_letter_plot_dictionary = {}
        for index, font_dictionary in enumerate(font_object_manager_given_characters.font_dictionaries):
            for font_size, font_object in font_dictionary.items():
                if font_object.path not in font_letter_plot_dictionary:
                    font_letter_plot_dictionary[font_object.path] = {}
                if font_size not in font_letter_plot_dictionary[font_object.path]:
                    font_letter_plot_dictionary[font_object.path][font_size] = {}

                if index in font_object_manager_given_characters.character_to_font_indicies["c"]:
                    new_coordinates_width_of_letter_height_of_letter = fontLetterPlotDictionaryInstantiator.get_letter_coordinates_width_and_height(font_object, "c")
                    
                    if new_coordinates_width_of_letter_height_of_letter:
                        if "c" not in font_letter_plot_dictionary[font_object.path][font_size]:
                            new_coordinates, width_of_letter, height_of_letter = new_coordinates_width_of_letter_height_of_letter
                            font_letter_plot_dictionary[font_object.path][font_size]["c"] = {}
                            font_letter_plot_dictionary[font_object.path][font_size]["c"]['start_coordinates'] = new_coordinates
                            font_letter_plot_dictionary[font_object.path][font_size]["c"]['width'] = width_of_letter
                            font_letter_plot_dictionary[font_object.path][font_size]["c"]['height'] = height_of_letter
                    else:
                        # If the character is supported in the glyph of the font file. But we were unable to render it with the PIL draw function.
                        font_object_manager_given_characters.character_to_font_indicies["c"].remove(index)
                        font_letter_plot_dictionary[font_object.path][font_size]["c"] = None

                for word in vocabulary:
                    if word == "dash_in_image_field" or word == "":
                        continue
                    else:
                        for character in word:
                            if index in font_object_manager_given_characters.character_to_font_indicies[character]:
                                if character not in font_letter_plot_dictionary[font_object.path][font_size]: # or not font_letter_plot_dictionary[font_object.path][font_size][text]):
                                    font_letter_plot_dictionary[font_object.path][font_size][character] = {}
                                    if character == " ":
                                        new_coordinates_width_of_letter_height_of_letter = fontLetterPlotDictionaryInstantiator.get_letter_coordinates_width_and_height(font_object, "c")
                                        if new_coordinates_width_of_letter_height_of_letter:
                                            new_coordinates, width_of_letter, height_of_letter = new_coordinates_width_of_letter_height_of_letter
                                            font_letter_plot_dictionary[font_object.path][font_size][character]['start_coordinates'] = new_coordinates
                                            font_letter_plot_dictionary[font_object.path][font_size][character]['width'] = width_of_letter
                                            font_letter_plot_dictionary[font_object.path][font_size][character]['height'] = height_of_letter
                                        else:
                                            font_object_manager_given_characters.character_to_font_indicies[character].remove(index)
                                            font_letter_plot_dictionary[font_object.path][font_size][character] = None
                                    else:
                                        new_coordinates_width_of_letter_height_of_letter = fontLetterPlotDictionaryInstantiator.get_letter_coordinates_width_and_height(font_object, character)
                                        if new_coordinates_width_of_letter_height_of_letter:
                                            new_coordinates, width_of_letter, height_of_letter = new_coordinates_width_of_letter_height_of_letter
                                            font_letter_plot_dictionary[font_object.path][font_size][character]['start_coordinates'] = new_coordinates
                                            font_letter_plot_dictionary[font_object.path][font_size][character]['width'] = width_of_letter
                                            font_letter_plot_dictionary[font_object.path][font_size][character]['height'] = height_of_letter
                                        else:
                                            font_object_manager_given_characters.character_to_font_indicies[character].remove(index)
                                            font_letter_plot_dictionary[font_object.path][font_size][character] = None
                                else:
                                    if not font_letter_plot_dictionary[font_object.path][font_size][character]:
                                        font_object_manager_given_characters.character_to_font_indicies[character].remove(index)
        return font_letter_plot_dictionary
    
    def get_letter_coordinates_width_and_height(font_object, text) -> tuple[tuple[int, int], int, int]:
        """
        This is a helper function to the main function of the class. 
        """
        multiplier = 0.3 # Helps put the character rendered into the view of the image we're drawing it on. 
        mask = font_object.getmask(text)
        bbox_mask = mask.getbbox() # This function does not always accurately place an encapsulating bounding box around the text, but it is a good estimate.
        text_bbox = bbox_mask
        if text_bbox:
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            image_width = round(text_width*10) # We make the image 6 times wider and taller than the text bbox, this is to help capture the text in the image should the .getbbox method doesn't get the bbox right.
            image_height = round(text_height*10)
            image = Image.new('RGB', (image_width, image_height), color=(255, 255, 255))
            text_start_y = round(image_height*multiplier) # Rather than drawing the character from the coordinates (0, 0), we start them at coordinates (20% of image width, 20% of image height) so that the characters are most often drawn in the image. This is not a flawless method. This is on the current to-do list up top as an item to be fixed.  
            text_start_x = round(image_width*multiplier)
            draw = ImageDraw.Draw(image)
            draw.text((text_start_x, text_start_y), text, font=font_object, fill=(0, 0, 0))
            image_as_array = np.array(image)        
            non_bg_mask = np.any(image_as_array != [255, 255, 255], axis=-1) # Find non-white pixels
            y_non_bg, x_non_bg = np.where(non_bg_mask) # Get the bounding box of non-background pixels
            if y_non_bg.size == 0 or x_non_bg.size == 0:
                return None
            else:
                true_y_pos_start, true_y_pos_end = y_non_bg.min(), y_non_bg.max()
                true_x_pos_start, true_x_pos_end = x_non_bg.min(), x_non_bg.max()
                new_coordinates = (text_start_x - true_x_pos_start + 1, text_start_y - true_y_pos_start + 1) # Calculate the new coordinates, width, and height
                width_of_letter = true_x_pos_end - true_x_pos_start + 1
                height_of_letter = true_y_pos_end - true_y_pos_start + 1
                return new_coordinates, width_of_letter, height_of_letter
        else:
            return None

class fontObjectManagerGivenVocabulary():
    def __init__(self, vocabulary: list, font_object_manager_given_characters: fontObjectManagerGivenCharacters):
        self.font_object_manager_given_characters = font_object_manager_given_characters
        # Check that all words in our vocabularly are supported by at least one font. 
        self.check_that_at_least_one_font_supports_all_characters(vocabulary)
        self.fonts_for_text_labels = self.get_font_for_text_labels(vocabulary)

    def check_that_at_least_one_font_supports_all_characters(self, vocabulary):
        temp_dict = {}
        set_of_characters = set()
        for word in vocabulary:
            if word != "dash_in_image_field":
                for character in word:
                    set_of_characters.add(character)
        all_characters = "".join(list(set_of_characters))
        reduced_text = self.font_object_manager_given_characters.get_reduced_text(all_characters)
        self.get_font_for_text_label(reduced_text, temp_dict)
        if temp_dict[reduced_text]:
            del temp_dict
        else:
            raise CustomError("There is no single font that supports all characters in the vocabulary. "
                              "There must be at least one font that has all characters in its glyph and the rendering of all the characters"
                              " must be supported by the PIL draw function as defined in the function: "
                              "fontLetterPlotDictionaryInstantiator.get_letter_coordinates_width_and_height()")

    def get_font_for_text_labels(self, vocabulary: list):
        fonts_for_text_labels = {}
        for text in vocabulary:
            self.get_font_for_text_label(text, fonts_for_text_labels)
        return fonts_for_text_labels

    def get_font_for_text_label(self, text: str, fonts_for_text_labels: dict):
        if text == "" or text == "dash_in_image_field":
            if text not in fonts_for_text_labels:
                fonts_for_text_labels[text] = []
                for index, _ in enumerate(self.font_object_manager_given_characters.font_dictionaries):
                    fonts_for_text_labels[text].append(index)
        else:
            reduced_text = self.font_object_manager_given_characters.get_reduced_text(text)
            reduced_text_with_c = reduced_text + "c"
            if reduced_text not in fonts_for_text_labels:
                # If the intersection is empty, this will return an empty list. 
                list_of_fonts_for_reduced_text = list(set.intersection(*[self.font_object_manager_given_characters.character_to_font_indicies[character] for character in reduced_text_with_c])) # For each label in our vocabulary, set it equal to a list of indicies that correspond to all the fonts that support that word.
                fonts_for_text_labels[reduced_text] = list_of_fonts_for_reduced_text

    def get_font_based_on_word(self, text: str, font_size: int) -> ImageFont:
        """
        This function gets a font object for a given word and font size.

        Args:
            text (str): This is a word from the vocabulary.
            font_size (int): This is the given font size we want the word to be. 
        """
        if text == "dash_in_image_field":
            reduced_text = text
        else:
            reduced_text = self.font_object_manager_given_characters.get_reduced_text(text)
        font_dict_index = random.choice(self.fonts_for_text_labels[reduced_text])
        return self.font_object_manager_given_characters.font_dictionaries[font_dict_index][font_size]

    def get_font_based_on_words(self, texts: list[str], font_size: int) -> ImageFont:
        list_of_sets = []
        for text in texts:
            if text != "dash_in_image_field":
                reduced_text = self.font_object_manager_given_characters.get_reduced_text(text)
            else:
                reduced_text = text
            list_of_font_dict_indicies = self.fonts_for_text_labels[reduced_text]
            list_of_sets.append(set(list_of_font_dict_indicies))
        intersection = list(set.intersection(*list_of_sets))
        font_dict_index = random.choice(intersection)
        return self.font_object_manager_given_characters.font_dictionaries[font_dict_index][font_size], font_dict_index

class numberManager():
    """
        This class determines what number should be given based on what was set in the config file
    """
    def __init__(self, config: dict, config_key: str, number_lower_bound_limit: int, number_upper_bound_limit: int):
        self.number_lower_bound_limit = number_lower_bound_limit
        self.number_upper_bound_limit = number_upper_bound_limit 
        self.number_config = config[config_key]
        self.config_key = config_key
        self.set_numbers()

    def set_numbers(self):
        """
        Set how numbers should be given. 
            If static, the upper and lower bound are the same.
            If uniform, set the upper and lower bounds.
            If gaussian, set the upper and lower bounds.  
        """
        if self.number_config['static']['bool']:
            self.number_lower_bound = self.number_config['static']['value']
            self.number_upper_bound = self.number_lower_bound
        elif self.number_config['uniform']['bool']:
            self.number_lower_bound = self.number_config['uniform']['lower_bound']
            self.number_upper_bound = self.number_config['uniform']['upper_bound']
        elif self.number_config['gaussian']['bool']:
            self.mean_number = self.number_config['gaussian']['mean']
            self.standard_deviation_number = self.number_config['gaussian']['standard_deviation']
            clip_values_at_number_of_std_deviations = self.number_config['gaussian']['clip_values_at_number_of_std_deviations']
            self.number_lower_bound = round(self.mean_number - self.standard_deviation_number*clip_values_at_number_of_std_deviations)
            self.number_upper_bound = round(self.mean_number + self.standard_deviation_number*clip_values_at_number_of_std_deviations)
        else:
            raise Exception(f"At least one of the boolean flags for {self.config_key} must be set.")
        if self.number_lower_bound > self.number_upper_bound:
            raise ValueError(f"The lower bound for {self.config_key} shouldn't be less than the upper bound.")
        elif self.number_lower_bound < self.number_lower_bound_limit:
            raise ValueError(f"The lower bound for {self.config_key} shouldn't be less than {self.number_lower_bound_limit}. If this seems wrong, user must define the lower bound limit upon instantiation of this class.")
        elif self.number_upper_bound > self.number_upper_bound_limit:
            raise ValueError(f"The lower bound for {self.config_key} shouldn't be more than {self.number_upper_bound_limit}. If this seems wrong, user must define the upper bound limit upon instantiation of this class")

    def get_lower_bound(self) -> int:
        return self.number_lower_bound
    
    def get_upper_bound(self) -> int:
        return self.number_upper_bound

    def get_number(self) -> int:
        if self.number_config['static']['bool']:
            return self.number_lower_bound
        elif self.number_config['uniform']['bool']:
            return random.randint(self.number_lower_bound, self.number_upper_bound)
        elif self.number_config['gaussian']['bool']:
            number = round(random.gauss(self.mean_number, self.standard_deviation_number))
            return max(self.number_lower_bound, min(self.number_upper_bound, number))
        else:
            raise Exception(f"At least one of the boolean flags for {self.config_key} must be set.")


class backgroundColorManager(numberManager):
    """
    This class handles what background color should be given.
    """
    def __init__(self, config: dict, config_key: str, number_lower_bound_limit: int = 0, number_upper_bound_limit: int = 255):
        super().__init__(config, config_key, number_lower_bound_limit, number_upper_bound_limit)

    def get_background_color(self) -> int:
        return self.get_number()
    

class fontColorManager(numberManager):
    """
    This class handles what font color should be given.
    """
    def __init__(self, config: dict, config_key: str, number_lower_bound_limit: int = 0, number_upper_bound_limit: int = 255):
        super().__init__(config, config_key, number_lower_bound_limit, number_upper_bound_limit)

    def get_font_color(self) -> int:
        return self.get_number()
    

class underlineColorManager(numberManager):
    """
    This class handles what underline color should be given.
    """
    def __init__(self, config: dict, config_key: str, number_lower_bound_limit: int = 0, number_upper_bound_limit: int = 255):
        super().__init__(config, config_key, number_lower_bound_limit, number_upper_bound_limit)

    def get_underline_color(self) -> int:
        return self.get_number()


class fontSizeManager(numberManager):
    """
    This class handles what font size should be given.
    """
    def __init__(self, config: dict, config_key: str, number_lower_bound_limit: int = 10, number_upper_bound_limit: int = 200):
        super().__init__(config, config_key, number_lower_bound_limit, number_upper_bound_limit)

    def get_font_size(self) -> int:
        return self.get_number()


# Class that allows for images can be padded in different ways to allow for words to be placed differently.
class padImage():
    """
    This class is intended to pad the generated image so that the generated word appears in different places on images generated.
    """
    def __init__(self, x_pad: float, y_pad: float):
        self.x_pad = x_pad
        self.y_pad = y_pad

    def pad_image(self, image: np.ndarray, font_size: int, background_color: int, underline_color: int = None, underline_start_pos: int = None) -> np.ndarray:
        """
        This is the main function of the class.
        """
        height, width, _ = image.shape
        new_height = int(height*self.y_pad)
        new_width = int(width*self.x_pad)
        y_above = np.random.randint(0, new_height)
        x_left = np.random.randint(0, new_width)
        new_underline_start_pos = y_above + underline_start_pos
        new_underline_end_pos = new_underline_start_pos + (font_size // 10)
        new_image_as_array = np.full((new_width, new_height, 3), fill_value=background_color)
        if underline_color:
            if new_underline_start_pos < new_height:
                new_image_as_array[new_underline_start_pos:new_underline_end_pos, :, :] = [underline_color, underline_color, underline_color]
        for i, y in enumerate(range((y_above-1), (y_above+height))):
            for j, x in enumerate(range((x_left-1), (x_left+width))):
                for k in range(3):
                    if image[i, j, k] > new_image_as_array[y, x, k]:
                        new_image_as_array[y, x, k] = image[i, j, k]
        return new_image_as_array


class configLoader():
    """
    This class loads the config file for the synthetic data generator.
    """
    def __init__(self, config_file_path: str):
        self.config_file_path = config_file_path

    def load_config(self) -> dict:
        """
        This function loads a .yaml file for the script to use. 
        """
        with open(self.config_file_path, 'r') as stream:
            try:
                config = yaml.safe_load(stream)
                return config
            except yaml.YAMLError as exc:
                print(exc)
                exit()


class loadFontsAndWeights():
    """
    This class loads a json file that contains the paths to different fonts and the associated weights that determine how often that 
    font should be seen. For example:

    {
        "path/to/font_1.ttf": 0.5,
        "path/to/font_2.otf": 0.25,
        "path/to/font_3.ttf: 0.25
    }

    A different class in this repo will sample these fonts appropriately with the weights given. In the example given above, 
    font_1 will have a 50% probability of being sampled where the other fonts will have a 25% change of being sampled, respectively. 
    """
    def __init__(self, fonts_and_weights_path):
        self.fonts_and_weights_path = fonts_and_weights_path

    def get_fonts_and_weights(self) -> dict:
        with open(self.fonts_and_weights_path, 'r') as json_in:
            return json.load(json_in)


class cubicBezierCurve():
    def __init__(self, x0: int, x1: int, x2: int, x3: int, y0: int, y1: int, y2: int, y3: int):
        self.x0 = x0
        self.x1 = x1
        self.x2 = x2
        self.x3 = x3
        self.y0 = y0
        self.y1 = y1
        self.y2 = y2
        self.y3 = y3

    def get_point_value_at_t(self, t):
        x = (1 - t)**3 * self.x0 + 3 * (1 - t)**2 * t * self.x1 + 3 * (1 - t) * t**2 * self.x2 + t**3 * self.x3
        y = (1 - t)**3 * self.y0 + 3 * (1 - t)**2 * t * self.y1 + 3 * (1 - t) * t**2 * self.y2 + t**3 * self.y3
        return round(x), round(y)

class drawDashesWithBezier():
    def __init__(self, height_range: tuple, width_range: tuple, x0_range: tuple, x1_range: tuple, x2_range: tuple, x3_range: tuple, y0_range: tuple, y1_range: tuple, y2_range: tuple, y3_range: tuple): 
        self.height_range = height_range
        if self.height_range[0] > self.height_range[1]:
            raise CustomError("The upper end of the height range should be greater than or equal to the lower range.")
        self.width_range = width_range
        if self.width_range[0] > self.width_range[1]:
            raise CustomError("The upper end of the width range should be greater than or equal to the lower range.")
        self.x0_range = x0_range
        self.x1_range = x1_range
        self.x2_range = x2_range
        self.x3_range = x3_range
        self.y0_range = y0_range
        self.y1_range = y1_range
        self.y2_range = y2_range
        self.y3_range = y3_range

    def get_height_and_width(self) -> tuple[int, int]:
        height = np.random.randint(self.height_range[0], self.height_range[1]+1)
        width = np.random.randint(self.width_range[0], self.width_range[1]+1)
        return height, width

    def get_coordinate_points(self, height: int, width: int):
        x0 = round(width*np.random.uniform(self.x0_range[0], self.x0_range[1]))
        x1 = round(width*np.random.uniform(self.x1_range[0], self.x1_range[1]))
        x2 = round(width*np.random.uniform(self.x2_range[0], self.x2_range[1]))
        x3 = round(width*np.random.uniform(self.x3_range[0], self.x3_range[1]))
        y0 = round(height*np.random.uniform(self.y0_range[0], self.y0_range[1]))
        y1 = round(height*np.random.uniform(self.y1_range[0], self.y1_range[1]))
        y2 = round(height*np.random.uniform(self.y2_range[0], self.y2_range[1]))
        y3 = round(height*np.random.uniform(self.y3_range[0], self.y3_range[1]))
        return x0, x1, x2, x3, y0, y1, y2, y3

    def get_dash_bezier_curve(self, x0: int, x1: int, x2: int, x3: int, y0: int, y1: int, y2: int, y3: int) -> cubicBezierCurve:
        return cubicBezierCurve(x0, x1, x2, x3, y0, y1, y2, y3)

    def get_dash_on_image(self, font_color: int, background_color: int) -> np.ndarray:
        height, width = self.get_height_and_width()
        x0, x1, x2, x3, y0, y1, y2, y3 = self.get_coordinate_points(height, width)
        cubic_bezier_curve = self.get_dash_bezier_curve(x0, x1, x2, x3, y0, y1, y2, y3)
        x_y_pairs = [cubic_bezier_curve.get_point_value_at_t(t) for t in np.linspace(0, 1, 1000)]

        image = np.full(shape=(height, width, 3), fill_value=background_color)

        line_thickness = height / np.random.uniform(13, 18)
        line_thickness_above = round(line_thickness/2)
        line_thickness_below = line_thickness_above + 1

        for (x, y) in x_y_pairs:
            image[(y-line_thickness_above):(y+line_thickness_below), x:x+1, :] = font_color

        return image

class drawWordOnImage():
    """
    This class generates a synthetic image and draws text on it.
    """ 
    def __init__(self, font_letter_plot_dictionary: dict, draw_dashes_with_bezier: drawDashesWithBezier, image_padder: padImage):
        self.font_letter_plot_dictionary = font_letter_plot_dictionary
        self.image_padder = image_padder
        self.draw_dashes_with_bezier = draw_dashes_with_bezier

    def get_word_data(self, text, font_object_path, font_size) -> tuple[int, int, int, int]:
        """
        Given a word (text), a font_object_path and a font_size, return the estimated height and width of the word on our image
        and the start coordinates for where the image should be drawn. 
        """
        if text == "":
            return font_size, font_size, 0, 0
        else:
            width_of_image = 0
            largest_height = 0
            x_coord_start = 0
            y_coord_start = -float("inf")
            for letter_pos, letter in enumerate(text):
                coordinates = self.font_letter_plot_dictionary[font_object_path][font_size][letter]['start_coordinates']
                if letter_pos == 0:
                    x_coord_start = coordinates[0]
                potential_y_coord_start = coordinates[1]
                if potential_y_coord_start > y_coord_start:
                    y_coord_start = potential_y_coord_start
                width = self.font_letter_plot_dictionary[font_object_path][font_size][letter]['width']
                width_of_image += int(width*3)
            for letter_pos, letter in enumerate(text):
                letter_height = self.font_letter_plot_dictionary[font_object_path][font_size][letter]['height']
                letter_y_coord = self.font_letter_plot_dictionary[font_object_path][font_size][letter]['start_coordinates'][1]
                largest_height = max(largest_height, (y_coord_start-letter_y_coord+letter_height))
            height_of_image = largest_height
            return width_of_image, height_of_image, x_coord_start, y_coord_start

    def trim_padding(self, image: np.ndarray, background_color: int) -> np.ndarray:
        """
        The rendered image is likely to be be slightly larger than the bounding box of the rendered word.
        This function will trim the image until it perfectly encapsulates the word. 
        """
        mask = np.any(image != background_color, axis=-1)
        y_indices, x_indices = np.where(mask)
        true_y_pos_start, true_y_pos_end = y_indices.min(), y_indices.max()
        true_x_pos_start, true_x_pos_end = x_indices.min(), x_indices.max()
        return image[true_y_pos_start:true_y_pos_end+1, true_x_pos_start:true_x_pos_end+1, :]

    def add_padding_to_adjust_to_transforms(self, image: np.ndarray, background_color: int) -> np.ndarray:
        """
        Some transformations create features beyond the bounding box that encapsulates the text in an image. As such, we want some wiggle room to ensure
        that these features are encapsulated. After this, the image may be trimmed again. 
        """
        height, width, depth = image.shape
        width_to_add_per_side = round(width*0.05)
        height_to_add_per_side = round(height*0.05)
        new_width = round(width + (2*width_to_add_per_side))
        new_height = round(height + (2*height_to_add_per_side))
        new_image = np.full(shape=(new_height, new_width, depth), fill_value=background_color)
        new_image[height_to_add_per_side:(height_to_add_per_side+height), width_to_add_per_side:(width_to_add_per_side+width), :] = image
        return new_image

    def create_image(self, text: str, font_object: ImageFont, background_color: int, font_color: int, width_of_image: int, height_of_image: int, x_coord_start: int, y_coord_start: int) -> np.ndarray:
        """
        Given a word, a font object, image background color, font color, image dimensions and text start coordinates, a synthetic image is created. 
        """
        if text == "":
            return np.array(Image.new('RGB', (width_of_image, height_of_image), color=(background_color, background_color, background_color)))
        else:
            image = Image.new('RGB', (width_of_image, height_of_image), color=(background_color, background_color, background_color))
            draw = ImageDraw.Draw(image)
            draw.text((x_coord_start, y_coord_start-1), text, font=font_object, fill=(font_color, font_color, font_color))
            image = np.array(image)
            image = self.trim_padding(image, background_color)
            image = self.add_padding_to_adjust_to_transforms(image, background_color)
            return image

    def get_underline_start_pos(self, font_object: ImageFont, font_size: int, y_coord_start: int) -> int:
        """
        To draw an underline under the word on the image, we determine the underline start position
        by finding the y-coordinate for where the bottom of the letter c would be on our given word. 
        """
        c_coordinates = self.font_letter_plot_dictionary[font_object.path][font_size]["c"]['start_coordinates']
        c_height = self.font_letter_plot_dictionary[font_object.path][font_size]["c"]["height"]
        underline_start_pos = (y_coord_start - c_coordinates[1]) + c_height
        return underline_start_pos
        
    def draw_underline(self, image: np.ndarray, font_size: int, underline_color: int, underline_start_pos: int) -> np.ndarray:
        """
        Draws an underline on our image.
        """
        underline_end_pos = underline_start_pos + (font_size // 10)
        if underline_start_pos < image.shape[0]:
            image[underline_start_pos:underline_end_pos, :, :] = [underline_color, underline_color, underline_color] 
        return image

    def get_image(self, text: str, get_underline: bool, font_size: int, background_color: int, font_color: int, font_object: ImageFont, underline_color: int = None) -> list[np.ndarray, int]:
        """
        This is the main function for this class. It returns a synthetically generated image. 
        """
        if text == "dash_in_image_field":
            image = self.draw_dashes_with_bezier.get_dash_on_image(font_color, background_color)
            underline_start_pos = round(image.shape[0]*.9)
        else:
            width_of_image, height_of_image, x_coord_start, y_coord_start = self.get_word_data(text, font_object.path, font_size)
            image = np.array(self.create_image(text, font_object, background_color, font_color, width_of_image, height_of_image, x_coord_start, y_coord_start))
            underline_start_pos = self.get_underline_start_pos(font_object, font_size, y_coord_start)
        if get_underline:
            image = self.draw_underline(image, font_size, underline_color, underline_start_pos)
        if self.image_padder:
            if get_underline:
                image = self.image_padder.pad_image(image, font_size, background_color, underline_color, underline_start_pos)
            else:
                image = self.image_padder.pad_image(image, font_size, background_color)
        return [image, underline_start_pos]

class drawWordOnImageInstantiator():
    """
    This class creates a drawWordOnImage object. 
    """
    @staticmethod
    def get_image_padder(x_and_y_pad: tuple[float]) -> padImage|None:
        if x_and_y_pad:
            return padImage(x_and_y_pad[0], x_and_y_pad[1])
        else:
            return None

    @staticmethod
    def get_draw_on_image_object(font_letter_plot_dictionary: dict, draw_dashes_with_bezier: drawDashesWithBezier, image_padder: padImage = None) -> drawWordOnImage:
        return drawWordOnImage(font_letter_plot_dictionary, draw_dashes_with_bezier, image_padder)

class Point():
    """
    This class represents a point object: (x, y) coordinate on the cardesian plane.
    """
    def __init__(self, point: list[float]):
        self.x = point[0]
        self.y = point[1]

    def get_point(self) -> tuple[int, int]:
        return (self.x, self.y)

class Quadrilateral():
    """
    This class represents a quadrilateral on the cardesian plane. 
    """
    def __init__(self, path_to_quadrilateral: str):
        self.points = self.load_points(path_to_quadrilateral)
        self.x_start = round(min([point_.x for point_ in self.points]))
        self.x_end = round(max([point_.x for point_ in self.points]))
        self.y_start = round(min([point_.y for point_ in self.points]))
        self.y_end = round(max([point_.y for point_ in self.points]))
        self.set_width()
        self.set_height()       

    def load_points(self, path_to_quadrilateral: str) -> list[float]:
        with open(path_to_quadrilateral, 'r') as json_in:
            dict_ = json.load(json_in)
            number_of_points = len(dict_["points"])
            if number_of_points != 4:
                raise CustomError(f"The quadrilateral should have 4 points. This object has {number_of_points} points.")
            else:
                return [Point(point) for point in dict_["points"]]

    def set_width(self):
        self.width =  (self.x_end-self.x_start)
    
    def set_height(self):
        self.height = (self.y_end-self.y_start)

    def get_width(self) -> int:
        return self.width
    
    def get_height(self) -> int:
        return self.height
        
class getBoundsForWindowOnBaseImageFromQuadrilateral():
    """
    This class determines the ranges for the x_start, x_end, y_start and y_end coordinates for a window on our base image that we might want to crop or merge a word into. 
    
    Args:
        quadrilateral: A Quadrilateral object that contains the points for the window that was plotted by a user. 
        x_start_left_range_percentage: This number indicates how far to the left from the mean left side of the quadrilateral we will allow the window to start from. It is calculated as (x_start_left_range_percentage)*(width of quadrilateral)
        x_start_right_range_percentage: This number indicates how far to the right from the mean left side of the quadrilateral we will allow the window to start from. It is calculated as (x_start_right_range_percentage)*(width of quadrilateral)
        x_end_left_range_percentage:  This number indicates how far to the left from the mean right side of the quadrilateral we will allow the window to end at. It is calculated as (x_end_left_range_percentage)*(width of quadrilateral)
        x_end_right_range_percentage: This number indicates how far to the right from the mean right side of the quadrilateral we will allow the window to end at. It is calculated as (x_end_right_range_percentage)*(width of quadrilateral)
        y_start_lower_range_percentage, y_start_higher_range_percentage, y_end_lower_range_percentage, y_end_higher_range_percentage: Same as above but for the y-axis and works off quadrilateral_height
    """
    def __init__(self, quadrilateral: Quadrilateral, x_start_left_range_percentage: float, x_start_right_range_percentage: float, x_end_left_range_percentage: float, x_end_right_range_percentage: float, y_start_lower_range_percentage: float, y_start_higher_range_percentage: float, y_end_lower_range_percentage: float, y_end_higher_range_percentage: float):
        self.quadrilateral = quadrilateral
        self.x_start_left_range_percentage = x_start_left_range_percentage
        self.x_start_right_range_percentage = x_start_right_range_percentage
        self.x_end_left_range_percentage = x_end_left_range_percentage
        self.x_end_right_range_percentage = x_end_right_range_percentage
        self.y_start_lower_range_percentage = y_start_lower_range_percentage
        self.y_start_higher_range_percentage = y_start_higher_range_percentage
        self.y_end_lower_range_percentage = y_end_lower_range_percentage
        self.y_end_higher_range_percentage = y_end_higher_range_percentage

    def get_bounds(self, mean_position: float, length_of_dimension: int, percentage_1: float, percentage_2: float) -> tuple[int, int]:
        """
        This is a helper function for the class's main function: get_bounds_for_word_on_base_image
        """
        start_pos = round(mean_position-(length_of_dimension*percentage_1))
        end_pos = round(mean_position+(length_of_dimension*percentage_2))
        return start_pos, end_pos

    def get_bounds_for_window_on_base_image(self) -> tuple[int, int, int, int, int, int, int, int]:
        """
        This gets the bounds in which the window can be placed on the base image.
        """
        # Change this so that there isn't a mean pos, just take the boundries of the bbox.
        width = self.quadrilateral.get_width()
        height = self.quadrilateral.get_height()
        x_start_lower_bound, x_start_upper_bound = self.get_bounds(self.quadrilateral.x_start, width, self.x_start_left_range_percentage, self.x_start_right_range_percentage)
        x_end_lower_bound, x_end_upper_bound = self.get_bounds(self.quadrilateral.x_end, width, self.x_end_left_range_percentage, self.x_end_right_range_percentage)
        y_start_lower_bound, y_start_upper_bound = self.get_bounds(self.quadrilateral.y_start, height, self.y_start_lower_range_percentage, self.y_start_higher_range_percentage)
        y_end_lower_bound, y_end_upper_bound = self.get_bounds(self.quadrilateral.y_end, height, self.y_end_lower_range_percentage, self.y_end_higher_range_percentage)
        return x_start_lower_bound, x_start_upper_bound, x_end_lower_bound, x_end_upper_bound, y_start_lower_bound, y_start_upper_bound, y_end_lower_bound, y_end_upper_bound

class determineNewBaseImageBounds():
    """
    If we are only generating images for parts of a base image then when we load in the base image, we only need the parts of the base image on which we
    will be merging or viewing. This class determines the new window for the partial base image that will be used. 
    """   
    @staticmethod
    def determine_new_bounds(bounds_for_windows: list[list]) -> tuple[int, int, int, int]:
        x_start, y_start = float("inf"), float("inf")
        x_end, y_end = -float("inf"), -float("inf")
        for bound_for_word in bounds_for_windows:
            x_start = min(x_start, bound_for_word[0])
            y_start = min(y_start, bound_for_word[4])
            x_end = max(x_end, bound_for_word[3])
            y_end = max(y_end, bound_for_word[7])
        return x_start, y_start, x_end, y_end

    @staticmethod
    def get_new_bounds(bounds_for_windows: list[list]) -> tuple[int, int, int, int]:
        x_start, y_start, x_end, y_end = determineNewBaseImageBounds.determine_new_bounds(bounds_for_windows)
        return x_start, y_start, x_end, y_end

class getNewBaseImage():
    """
    This class gets a new base image based on the information gathered from the determineNewBaseImageBounds class
    """
    @staticmethod
    def get_new_base_image(base_image: np.ndarray, x_start_lower_bound: int, y_start_lower_bound: int, x_end_upper_bound: int, y_end_upper_bound: int) -> np.ndarray:
        return base_image[y_start_lower_bound:(y_end_upper_bound+1), x_start_lower_bound:(x_end_upper_bound+1), :]

class determineNewWindowBounds():
    """
    If using a partial base image for image generation. Then the original bounds for the windows for the full base image will need to be adjusted to ensure that they have correct new bounds on the partial base image. 
    """
    @staticmethod
    def get_new_bounds(bounds_for_words: list, x_min: int, y_min: int) -> tuple[int, int, int, int, int, int, int, int]:
        """
        The original base image started from coordinates (0, 0). The partial base image will technically start from coordinates (0, 0) as well, but based on the coordinates from the original base image,
        will have start_coordinates (x_min, y_min). Using this information, we can update the coordinates for our windows such that they reflect the coordinates on the partial base image.
        """
        x_start_lower_bound = bounds_for_words[0] - x_min
        x_start_upper_bound = bounds_for_words[1] - x_min
        x_end_lower_bound = bounds_for_words[2] - x_min
        x_end_upper_bound = bounds_for_words[3] - x_min
        y_start_lower_bound = bounds_for_words[4] - y_min
        y_start_upper_bound = bounds_for_words[5] - y_min
        y_end_lower_bound = bounds_for_words[6] - y_min
        y_end_upper_bound = bounds_for_words[7] - y_min
        return x_start_lower_bound, x_start_upper_bound, x_end_lower_bound, x_end_upper_bound, y_start_lower_bound, y_start_upper_bound, y_end_lower_bound, y_end_upper_bound

class Window():
    """
    This is the base class for windows (ranges when we might crop a base image or merge a word).
    """
    def __init__(self, x_start_lower_bound: int, x_start_upper_bound: int, x_end_lower_bound: int, x_end_upper_bound: int, y_start_lower_bound: int, y_start_upper_bound: int, y_end_lower_bound: int, y_end_upper_bound: int):
        self.check_bounds(x_start_lower_bound, x_start_upper_bound, "x_start")
        self.check_bounds(x_end_lower_bound, x_end_upper_bound, "x_end")
        self.check_bounds(y_start_lower_bound, y_start_upper_bound, "y_start")
        self.check_bounds(y_end_lower_bound, y_end_upper_bound, "y_end")

        self.x_start_lower_bound = x_start_lower_bound
        self.x_start_upper_bound = x_start_upper_bound
        self.x_end_lower_bound = x_end_lower_bound
        self.x_end_upper_bound = x_end_upper_bound
        self.y_start_lower_bound = y_start_lower_bound
        self.y_start_upper_bound = y_start_upper_bound
        self.y_end_lower_bound = y_end_lower_bound
        self.y_end_upper_bound = y_end_upper_bound

    def check_bounds(self, lower_bound: int, upper_bound: int, window_side: str):
        if lower_bound > upper_bound:
            raise CustomError(f"The lower bound is greater than the upper bound for the {window_side} part of the window.")

    def get_start_or_end(self, lower_bound: int, upper_bound: int):
        if lower_bound == upper_bound:
            return lower_bound
        else:
            return np.random.randint(lower_bound, upper_bound)
        
    def get_starts_and_ends(self):
        # Determine the bounds on the base image within which we'll merge our word image.
        x_start = self.get_start_or_end(self.x_start_lower_bound, self.x_start_upper_bound)
        x_end = self.get_start_or_end(self.x_end_lower_bound, self.x_end_upper_bound)
        y_start = self.get_start_or_end(self.y_start_lower_bound, self.y_start_upper_bound)
        y_end = self.get_start_or_end(self.y_end_lower_bound, self.y_end_upper_bound)
        return x_start, x_end, y_start, y_end

    def update_bounds(self, new_x_min: int, new_y_min: int):
        """
        Update the window based on the start coordinates for the base image.
        """
        self.x_start_lower_bound -= new_x_min
        self.x_start_upper_bound -= new_x_min
        self.x_end_lower_bound -= new_x_min
        self.x_end_upper_bound -= new_x_min
        self.y_start_lower_bound -= new_y_min
        self.y_start_upper_bound -= new_y_min
        self.y_end_lower_bound -= new_y_min
        self.y_end_upper_bound -= new_y_min

    def get_bounds(self) -> tuple[int, int, int, int, int, int, int, int]:
        return [self.x_start_lower_bound, self.x_start_upper_bound, self.x_end_lower_bound, self.x_end_upper_bound, self.y_start_lower_bound, self.y_start_upper_bound, self.y_end_lower_bound, self.y_end_upper_bound]

class mergeWordImageOnBaseImage(Window):
    """
    This class takes the bounds for a window where we want a word image to be merged on the base image, and takes in a word image, resizes it and merges it onto the base image. 
    The merging works by comparing the pixels of the word image with the pixels from the base image and the darker pixel is kept.
    Users should take care when generating and transforming the word image such that relevant features are dark enough to appear on the merged image. 
    """
    def __init__(self, x_start_lower_bound: int, x_start_upper_bound: int, x_end_lower_bound: int, x_end_upper_bound: int, y_start_lower_bound: int, y_start_upper_bound: int, y_end_lower_bound: int, y_end_upper_bound: int, new_width_multiplier_start: float, new_width_multiplier_end: float):
        super().__init__(x_start_lower_bound, x_start_upper_bound, x_end_lower_bound, x_end_upper_bound, y_start_lower_bound, y_start_upper_bound, y_end_lower_bound, y_end_upper_bound)
        self.new_width_multiplier_start = new_width_multiplier_start
        self.new_width_multiplier_end = new_width_multiplier_end

    def merge_word_image_and_base_image(self, word_image_as_array: np.ndarray, underline_start_pos_from_word_image: int, base_image: np.ndarray) -> np.ndarray:
        """
        This is main function of the mergeWordImageOnBaseImage. It chooses a place on the window based on the bounds for each position: left, right, top and bottom,
            then resizes the word image to that given space, then it merges the word image with the base image and returns the base image
        """
        x_start, x_end, y_start, y_end = self.get_starts_and_ends()

        window_width = x_end - x_start
        window_height = y_end - y_start
        word_image_height, word_image_width, _ = word_image_as_array.shape
        new_height = round((word_image_height/underline_start_pos_from_word_image)*window_height)
        new_width = round((new_height/word_image_height)*word_image_width*(np.random.uniform(self.new_width_multiplier_start, self.new_width_multiplier_end)))

        if window_width < new_width:
            new_width = window_width

        resize = A.Resize(height=new_height, width=new_width) # Resize our word image to the size of the window for merging onto the base image. 
        word_image_as_array_resized = resize(image=word_image_as_array)["image"]

        merge_x_start = x_start
        if new_width < window_width: # If the new width of our word image is smaller than the width of the window on the base image we're to merge on, let the x-position vary from the start of the window so that there is variation in word placement. 
            # TODO: Make this a parameter that the user can influence. Mark 3
            difference = window_width-new_width
            difference_scaled = int(difference/20)
            merge_x_start = x_start + np.clip(int(np.random.chisquare(3)*difference_scaled), 0, difference)

        # For every pixel value in the word image that is smaller (darker) then the corresponding pixel value in the window of the base image, set the corresponding pixel value in the base image to that smaller pixel value. 
        for i, y in enumerate(range(y_start, min((y_start+new_height), base_image.shape[0]))):
            for j, x in enumerate(range(merge_x_start, (merge_x_start+new_width))):
                for k in range(3):
                    if base_image[y, x, k] > word_image_as_array_resized[i, j, k]:
                        base_image[y, x, k] = word_image_as_array_resized[i, j, k]

        return base_image

class mergeWordImageOnBaseImageInstantiator():
    """
    This class creates a mergeWordImageOnBaseImage object based on a config file. 
    """
    @staticmethod
    def get_merge_word_image_on_base_image_object(config: dict) -> mergeWordImageOnBaseImage:
        path_to_quadrilateral = config["path_to_quadrilateral"]
        x_start_left_range_percentage = config["x_start_left_range_percentage"]
        x_start_right_range_percentage = config["x_start_right_range_percentage"]
        x_end_left_range_percentage = config["x_end_left_range_percentage"]
        x_end_right_range_percentage = config["x_end_right_range_percentage"]
        y_start_lower_range_percentage = config["y_start_lower_range_percentage"]
        y_start_higher_range_percentage = config["y_start_higher_range_percentage"]
        y_end_lower_range_percentage = config["y_end_lower_range_percentage"]
        y_end_higher_range_percentage = config["y_end_higher_range_percentage"]
        new_width_multiplier_start = config["new_width_multiplier_start"]
        new_width_multiplier_end = config["new_width_multiplier_end"]
        quadrilateral = Quadrilateral(path_to_quadrilateral)
        x_start_lower_bound, x_start_upper_bound, x_end_lower_bound, x_end_upper_bound, y_start_lower_bound, y_start_upper_bound, y_end_lower_bound, y_end_upper_bound = getBoundsForWindowOnBaseImageFromQuadrilateral(quadrilateral, x_start_left_range_percentage, x_start_right_range_percentage, x_end_left_range_percentage, x_end_right_range_percentage, y_start_lower_range_percentage, y_start_higher_range_percentage, y_end_lower_range_percentage, y_end_higher_range_percentage).get_bounds_for_window_on_base_image()
        return mergeWordImageOnBaseImage(x_start_lower_bound, x_start_upper_bound, x_end_lower_bound, x_end_upper_bound, y_start_lower_bound, y_start_upper_bound, y_end_lower_bound, y_end_upper_bound, new_width_multiplier_start, new_width_multiplier_end)

class cropMergedImageToViewSize(Window):
    """
    This class crops the merged image down to a random size (bounds for size determined by user) to add variation to our images. 
    """
    def __init__(self, x_start_lower_bound: int, x_start_upper_bound: int, x_end_lower_bound: int, x_end_upper_bound: int, y_start_lower_bound: int, y_start_upper_bound: int, y_end_lower_bound: int, y_end_upper_bound: int):
        super().__init__(x_start_lower_bound, x_start_upper_bound, x_end_lower_bound, x_end_upper_bound, y_start_lower_bound, y_start_upper_bound, y_end_lower_bound, y_end_upper_bound)

    def crop_image(self, image: np.ndarray) -> np.ndarray:
        """
        This is the main function of this class that crops the merged image down to the bounds selected below. 

        Args:
            image: an np.ndarray of our image.
        """
        x_start, x_end, y_start, y_end = self.get_starts_and_ends()
        return image[y_start:(y_end+1), x_start:(x_end+1), :]

class cropMergedImageToViewSizeInstantiator():
    """
    This class creates cropMergedImageToViewSize objects.
    """
    @staticmethod
    def get_object(path_to_view_size_quadrilateral: str, x_start_left_range_percentage: float, x_start_right_range_percentage: float, x_end_left_range_percentage: float, x_end_right_range_percentage: float, y_start_lower_range_percentage: float, y_start_higher_range_percentage: float, y_end_lower_range_percentage: float, y_end_higher_range_percentage: float) -> cropMergedImageToViewSize:
        return cropMergedImageToViewSize(*getBoundsForWindowOnBaseImageFromQuadrilateral(Quadrilateral(path_to_view_size_quadrilateral), x_start_left_range_percentage, x_start_right_range_percentage, x_end_left_range_percentage, x_end_right_range_percentage, y_start_lower_range_percentage, y_start_higher_range_percentage, y_end_lower_range_percentage, y_end_higher_range_percentage).get_bounds_for_window_on_base_image())

class transformManager():
    """
    This class manages transforms for the data generator.
    """
    def __init__(self, transforms: list):
        self.transforms = self.set_composed_transforms(transforms)

    def set_composed_transforms(self, transforms: list) -> A.Compose|None:
        if transforms:
            return A.Compose(transforms)
        else:
            return None
        
    def transform(self, image: np.ndarray) -> np.ndarray:
        if self.transforms:
            return self.transforms(image=image)["image"]
        else:
            return image
        
class transformWordImagesForBaseImage(transformManager):
    # TODO: Fix the replay transforms
    """
    This class is made to manage transformations for word images that are to be merged on the base image. 

    Args:
        same_transforms: A list of Albumentation transforms. Use: If a base image has multiple fields to be filled with words, we often want the exact same transformation to happen to all of these words. These are those transformations. 
        different_transformations: A list of Albumentation transforms. Use: These transforms are applied to each word image for a base image and the exact transformation aren\'t applied across these word images.
    
    If no transformations are given, none will be applied. 
    """
    def __init__(self, same_transforms: list, different_transforms: list):
        super().__init__(different_transforms)
        self.different_transforms = self.transforms
        self.same_transforms = self.set_replay_transforms(same_transforms)

    def set_replay_transforms(self, transforms: list) -> A.ReplayCompose|None:
        if transforms:
            return A.ReplayCompose(transforms)
        else:
            return None

    def transform(self, images_as_arrays: list[np.ndarray]) -> list[np.ndarray]:
        if self.different_transforms:
            if self.same_transforms: # Same transforms and different transforms.
                replay_dict = self.same_transforms(image=images_as_arrays[0])
                same_transformed_images = [A.ReplayCompose.replay(replay_dict['replay'], image=image_as_array)['image'] for image_as_array in images_as_arrays]
                return [self.different_transforms(image=image_as_array)["image"] for image_as_array in same_transformed_images]
            else: # Different transforms only.
                return [self.different_transforms(image=image_as_array)["image"] for image_as_array in images_as_arrays]
        else:
            if self.same_transforms: # Same transforms only.
                replay_dict = self.same_transforms(image=images_as_arrays[0])
                return [A.ReplayCompose.replay(replay_dict['replay'], image=image_as_array)['image'] for image_as_array in images_as_arrays]
            else: # No transforms applied.
                return images_as_arrays

class transformBaseImage(transformManager):
    """
    This is the transform manager for the base image
    """
    def __init__(self, transforms):
        super().__init__(transforms)

class transformMergedImage(transformManager):
    """
    This is the transform manager for the merged images.
    """
    def __init__(self, transforms):
        super().__init__(transforms)

class mergeWordImagesOnBaseImage():
    """
    This class handles multiple mergeWordImageOnBaseImage objects and their corresponding drawWordOnImage objects and sequentially merges words onto the base image. 
    """
    def __init__(self, base_image_transforms: list, word_image_same_transforms: list, word_image_different_transforms: list, merged_image_transforms: list, config: dict, background_color_manager: backgroundColorManager, font_color_manager: fontColorManager, font_size_manager: fontSizeManager):
        self.base_image_transform_manager = transformBaseImage(base_image_transforms)
        self.word_image_transform_manager = transformWordImagesForBaseImage(word_image_same_transforms, word_image_different_transforms)
        self.merged_image_transform_manager = transformMergedImage(merged_image_transforms)
        self.crop_merged_image_to_view_size_object = self.get_cropped_merged_image_to_view_size_object(config)
        self.background_color_manager = background_color_manager
        self.font_color_manager = font_color_manager
        self.font_size_manager = font_size_manager
        self.fields = self.get_fields(config)
        self.field_to_vocab_manager = self.get_field_to_vocab_manager(config)
        self.field_to_merge_word_image_on_base_image = self.get_field_to_merge_word_image_on_base_image(config)
        self.all_vocabulary = self.get_all_vocab()
        self.font_object_manager_given_characters = self.get_font_object_manager_given_characters(config)
        self.font_letter_plot_dictionary = fontLetterPlotDictionaryInstantiator.get_font_letter_plot_dictionary(self.font_object_manager_given_characters, self.all_vocabulary)
        self.font_object_manager_given_vocabulary = fontObjectManagerGivenVocabulary(self.all_vocabulary, self.font_object_manager_given_characters)
        self.fields_to_draw_dashes = self.get_field_to_draw_dashes_with_bezier(config)
        self.field_to_draw_word_on_image_object = self.get_draw_word_on_image_objects()
        self.base_image, new_x_min, new_y_min = self.get_image_base_and_image_base_start_coordinates(config)
        self.update_window_bounds(new_x_min, new_y_min)
        self.format_string = self.get_format_string(config)
        self.fields_to_input_into_format_string = self.get_fields_to_input_into_format_string(config)
        self.check_fields_match()

    def check_fields_match(self):
        set_of_fields = set(self.fields)
        for field in self.fields_to_input_into_format_string:
            if field not in set_of_fields:
                raise CustomError("You have a field listed in the fields you want to input into your format string that is not listed among the fields "
                                  f"in the configuration file. The of issue is called: \"{field}\". Ensure that the name of the fields in the config match the name of the field you are attempting to "
                                  "insert into the format string.")
        
        fields_to_text_for_format_string = {field:"a" for field in self.fields_to_input_into_format_string}
        try:
            string_ = self.format_string.format(**fields_to_text_for_format_string)
            del string_
        except Exception as e:
            raise CustomError(f"Error: Check that the fields listed in your format string match the fields listed in the fields_to_input_into_format_string variable in the config file. The field: {e}, doesn't match.")
        

    def get_cropped_merged_image_to_view_size_object(self, config: dict) -> cropMergedImageToViewSize|None:
        """
        This function gets a cropMergedImageToViewSizeInstantiator object.
        """
        if config["partial_base_image"]["bool"]:
            # TODO: Check here if the bounds are what we would expect them to be. 
            view_window_path = config["partial_base_image"]["view_window_path"]
            x_start_left_range_percentage = config["partial_base_image"]["x_start_left_range_percentage"]
            x_start_right_range_percentage = config["partial_base_image"]["x_start_right_range_percentage"]
            x_end_left_range_percentage = config["partial_base_image"]["x_end_left_range_percentage"]
            x_end_right_range_percentage = config["partial_base_image"]["x_end_right_range_percentage"]
            y_start_lower_range_percentage = config["partial_base_image"]["y_start_lower_range_percentage"]
            y_start_higher_range_percentage = config["partial_base_image"]["y_start_higher_range_percentage"]
            y_end_lower_range_percentage = config["partial_base_image"]["y_end_lower_range_percentage"]
            y_end_higher_range_percentage = config["partial_base_image"]["y_end_higher_range_percentage"]
            return cropMergedImageToViewSizeInstantiator.get_object(view_window_path, x_start_left_range_percentage, x_start_right_range_percentage, x_end_left_range_percentage, x_end_right_range_percentage, y_start_lower_range_percentage, y_start_higher_range_percentage, y_end_lower_range_percentage, y_end_higher_range_percentage)
        else:
            return None
        
    def get_fields(self, config: dict) -> list[str]:
        """
        This function gets the fields that we want to paste on our base image.
        """
        fields = []
        for field in config["fields"]:
            fields.append(field)
        return fields
    
    def get_field_to_vocab_manager(self, config: dict) -> dict:
        """
        This function yields a vocabManager object for each field we are interested in representing synthetically.
        """
        field_to_vocab_manager = {}
        for field in self.fields:
            vocab_manager = vocabManager(config["fields"][field]["path_to_vocabulary"])
            field_to_vocab_manager[field] = vocab_manager
        return field_to_vocab_manager
    
    def get_field_to_merge_word_image_on_base_image(self, config) -> dict:
        """
        This function yields a mergeWordImageOnBaseImage object for each field we are interested in representing synthetically. 
        """
        field_to_merge_word_image_on_base_image = {}
        for field in self.fields:
            merge_word_image_on_base_image = mergeWordImageOnBaseImageInstantiator.get_merge_word_image_on_base_image_object(config["fields"][field])
            field_to_merge_word_image_on_base_image[field] = merge_word_image_on_base_image
        return field_to_merge_word_image_on_base_image

    def get_field_to_draw_dashes_with_bezier(self, config) -> dict:
        """
        This function yields a drawDashesWithBezier object for each field we are interested in representing synthetically. 
        """
        field_to_draw_dashes_with_bezier = {}
        for field in self.fields:
            bezier_dash_dict = config["fields"][field]["bezier_dash"]
            height_range = bezier_dash_dict["height_range"]
            width_range = bezier_dash_dict["width_range"]
            x0_range = bezier_dash_dict["x0_range"]
            x1_range = bezier_dash_dict["x1_range"]
            x2_range = bezier_dash_dict["x2_range"]
            x3_range = bezier_dash_dict["x3_range"]
            y0_range = bezier_dash_dict["y0_range"]
            y1_range = bezier_dash_dict["y1_range"]
            y2_range = bezier_dash_dict["y2_range"]
            y3_range = bezier_dash_dict["y3_range"]
            field_to_draw_dashes_with_bezier[field] = drawDashesWithBezier(height_range, width_range, x0_range, x1_range, x2_range, x3_range, y0_range, y1_range, y2_range, y3_range)
        return field_to_draw_dashes_with_bezier

    def get_draw_word_on_image_objects(self) -> dict:
        """
        This function yields a drawWordOnImage object for each field we are interested in representing synthetically. 
        """
        field_to_draw_word_on_image_object = {}
        for field in self.fields:
            draw_dash_object = self.fields_to_draw_dashes[field]
            draw_word_on_image_object = drawWordOnImageInstantiator.get_draw_on_image_object(self.font_letter_plot_dictionary, draw_dash_object)
            field_to_draw_word_on_image_object[field] = draw_word_on_image_object
        return field_to_draw_word_on_image_object

    def get_all_vocab(self) -> list[str]:
        """
        This function gathers all the words from the various vocabularies we have, collects them in a single list and returns the list.
        """
        all_vocabulary = []
        for vocab_manager in self.field_to_vocab_manager.values():
            all_vocabulary += vocab_manager.vocabulary
        return all_vocabulary

    def get_font_object_manager_given_characters(self, config: dict) -> fontObjectManagerGivenCharacters:
        """
        This function yields a fontObjectManagerGivenCharacters object for our collected vocabulary. 
        """
        fonts_and_weights = config["path_to_fonts_and_weights_json"]
        font_size_lower_bound = self.font_size_manager.get_lower_bound()
        font_size_upper_bound = self.font_size_manager.get_upper_bound()
        return fontObjectManagerGivenCharacters(self.all_vocabulary, fonts_and_weights, font_size_lower_bound, font_size_upper_bound)

    def get_image_base_and_image_base_start_coordinates(self, config: dict) -> tuple[np.ndarray, int, int]:
        """
        This function returns the full or partial base image that we will merge word images onto. 
            It also returns the start coordinates for the given image that encapsulates all other 
            windows on the image of interest so that we can crop the full image to make our computation faster. 
            The coordinates are returned so that we can update the coordinate points of our other windows
            on the base image for our different fields as well. 
        """
        image = Image.open(config["path_to_base_image"])
        rgb_image = image.convert("RGB")
        full_image = np.array(rgb_image)
        if config["partial_base_image"]["bool"]:
            bounds_for_windows = []
            for merge_word_image_on_base_image in self.field_to_merge_word_image_on_base_image.values():
                bounds_for_windows.append(merge_word_image_on_base_image.get_bounds())
            bounds_for_windows.append(self.crop_merged_image_to_view_size_object.get_bounds())
            x_start, y_start, x_end, y_end = determineNewBaseImageBounds.get_new_bounds(bounds_for_windows)
            partial_image = getNewBaseImage.get_new_base_image(full_image, x_start, y_start, x_end, y_end)
            return partial_image, x_start, y_start
        else:
            return full_image, 0, 0
        
    def update_window_bounds(self, new_x_min: int, new_y_min: int):
        """
        If the user plotted a quadrilateral on the full base image that is of interest, and the base image is going to be
            cropped down then the coordinates of the quadrilateral need to be updated as well. 
        """
        for merge_word_image_on_base_image in self.field_to_merge_word_image_on_base_image.values():
            merge_word_image_on_base_image.update_bounds(new_x_min, new_y_min)
        self.crop_merged_image_to_view_size_object.update_bounds(new_x_min, new_y_min)

    def get_format_string(self, config: dict) -> str:
        """
        This function returns a format string that can be filled in depending on how the user wants text output from
        our model to look like. 
        """
        format_string_path = config["partial_base_image"]["format_string_path"]
        with open(format_string_path, 'r') as format_string_in:
            return format_string_in.read()

    def get_fields_to_input_into_format_string(self, config: dict) -> list[str]:
        """
        This function returns a list of fields from our config file that we want to input into our format string.
        """
        return config["partial_base_image"]["fields_to_input_into_format_string"]

    def create_fields_to_text_for_format_string(self, fields_to_generated_text: dict) -> dict:
        """
        This function gets the fields of interest to input into our format string from the dict of generated text that is created when merging
        word images onto the base image.

        Args:
            fields_to_generated_text: This is a dict object that maps a given field to a generated text from the vocabularly from this field. 
        """
        fields_to_text_for_format_string = {field:fields_to_generated_text[field] for field in self.fields_to_input_into_format_string}
        return fields_to_text_for_format_string

    def get_base_image_merged_with_word_images(self, get_text_randomly: bool) -> tuple[np.ndarray, str]:
        """
        This is the main function of the class. It takes a copy of the base image, word images, merges them, applies transforms to different images, not necessarily in that order.

        Args:
            get_text_randomly: This is a boolean value that determines if text is to be randomly sampled from our vocabulary.  
        """
        # make a copy of the base image
        base_image = self.base_image.copy()

        # transform the base image
        transformed_base_image = self.base_image_transform_manager.transform(base_image)

        # Get the font_size as well as the background color 
        font_size = self.font_size_manager.get_font_size()
        background_color = self.background_color_manager.get_background_color()

        fields_to_generated_text = {}
        fields_to_generated_word_images = {}
        fields_to_generated_word_images_underline_start_pos = {}

        # Get the text for each field
        for field in self.fields:
            fields_to_generated_text[field] = self.field_to_vocab_manager[field].get_text(get_text_randomly)

        texts = list(fields_to_generated_text.values())

        # Get a font object based on words
        font_object, _ = self.font_object_manager_given_vocabulary.get_font_based_on_words(texts, font_size)

        track_fields = []
        track_images = []
        track_underlines = []

        # Generate the images and underline start positions for each field
        for field in self.fields:
            text = fields_to_generated_text[field]
            font_color = self.font_color_manager.get_font_color()
            image, underline_start_pos = self.field_to_draw_word_on_image_object[field].get_image(text, False, font_size, background_color, font_color, font_object)
            fields_to_generated_word_images[field] = image
            fields_to_generated_word_images_underline_start_pos[field] = underline_start_pos
            track_fields.append(field)
            track_images.append(image)
            track_underlines.append(underline_start_pos)

        transformed_word_images = self.word_image_transform_manager.transform(track_images)

        for field, transformed_word_image, underline_start_pos in zip(track_fields, transformed_word_images, track_underlines):
            transformed_base_image = self.field_to_merge_word_image_on_base_image[field].merge_word_image_and_base_image(transformed_word_image, underline_start_pos, transformed_base_image)

        # crop the merged image
        cropped_transformed_base_image = self.crop_merged_image_to_view_size_object.crop_image(transformed_base_image)

        # transform the merged image
        transformed_merged_image = self.merged_image_transform_manager.transform(cropped_transformed_base_image)

        fields_to_text_for_format_string = self.create_fields_to_text_for_format_string(fields_to_generated_text)

        # return the cropped and transformed image
        return transformed_merged_image, self.format_string.format(**fields_to_text_for_format_string)