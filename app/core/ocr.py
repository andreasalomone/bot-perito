from PIL import Image
import pytesseract


def ocr(file_obj) -> str:
    return pytesseract.image_to_string(Image.open(file_obj))
