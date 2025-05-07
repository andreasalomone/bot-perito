import pytesseract
from PIL import Image


def ocr(file_obj) -> str:
    return pytesseract.image_to_string(Image.open(file_obj))
