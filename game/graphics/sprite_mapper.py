from game.model.pieces import get_color, get_type, is_empty


def piece_to_sprite_folder(piece):
    if is_empty(piece):
        raise ValueError("Empty cell has no sprite folder")

    piece_type = get_type(piece).upper()
    color = get_color(piece).upper()

    return piece_type + color