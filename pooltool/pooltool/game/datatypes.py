from pooltool.utils.strenum import StrEnum


class GameType(StrEnum):
    """An Enum for supported game types

    Attributes:
        EIGHTBALL:
        NINEBALL:
        THREECUSHION:
        SNOOKER:
        SUMTOTHREE:
        RUSSIAN_PYRAMID_FREE:
        RUSSIAN_PYRAMID_COMBINED:
        RUSSIAN_PYRAMID_DYNAMIC:
        RUSSIAN_PYRAMID_CLASSIC:
    """

    EIGHTBALL = "Eight Ball"
    NINEBALL = "Nine Ball"
    THREECUSHION = "Three Cushion"
    SNOOKER = "Snooker"
    SUMTOTHREE = "Sum to Three"
    RUSSIAN_PYRAMID_FREE = "Free Pyramid"
    RUSSIAN_PYRAMID_COMBINED = "Combined Pyramid"
    RUSSIAN_PYRAMID_DYNAMIC = "Dynamic Pyramid"
    RUSSIAN_PYRAMID_CLASSIC = "Classic Pyramid"
