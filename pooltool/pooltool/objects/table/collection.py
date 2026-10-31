from pooltool.game.datatypes import GameType
from pooltool.objects.table.specs import (
    BilliardTableSpecs,
    PocketTableSpecs,
    SnookerTableSpecs,
    TableModelDescr,
    TableSpecs,
    TableType,
)
from pooltool.utils.strenum import StrEnum


class TableName(StrEnum):
    """An Enum specifying table names.

    Attributes:
        SEVEN_FOOT_SHOWOOD:
        SNOOKER_GENERIC:
        BILLIARD_WIP:
        SUMTOTHREE_WIP:
        RUSSIAN_PYRAMID_GENERIC:
    """

    SEVEN_FOOT_SHOWOOD = "7 Ft Showood"
    SNOOKER_GENERIC = "Generic Snooker"
    BILLIARD_WIP = "Billiard (work in progress)"
    SUMTOTHREE_WIP = "Sum to Three (work in progress)"
    RUSSIAN_PYRAMID_GENERIC = "Generic Russian Pyramid"


TABLE_SPECS: dict[TableName, TableSpecs] = {
    TableName.SEVEN_FOOT_SHOWOOD: PocketTableSpecs(
        l=1.9812,
        w=1.9812 / 2,
        cushion_width=2 * 2.54 / 100,
        cushion_height=0.64 * 2 * 0.028575,
        corner_pocket_width=0.118,
        corner_pocket_angle=5.3,
        corner_pocket_depth=0.0417,
        corner_pocket_radius=0.062,
        corner_jaw_radius=0.02095,
        side_pocket_width=0.137,
        side_pocket_angle=7.14,
        side_pocket_depth=0.0685,
        side_pocket_radius=0.0645,
        side_jaw_radius=0.00795,
        height=0.708,
        lights_height=1.99,
        model_descr=TableModelDescr(name="seven_foot_showood"),
    ),
    TableName.SNOOKER_GENERIC: SnookerTableSpecs(
        l=3.569,
        w=1.778,
        cushion_width=47.63 / 1000,
        cushion_height=0.039,
        corner_pocket_width=80.14 / 1000,
        corner_pocket_angle=0,
        corner_pocket_depth=67.35 / 1000,
        corner_pocket_radius=88.9 / 1000,
        corner_jaw_radius=88.90 / 1000,
        side_pocket_width=84.57 / 1000,
        side_pocket_angle=0,
        side_pocket_depth=51.59 / 1000,
        side_pocket_radius=53.19 / 1000,
        side_jaw_radius=66.90 / 1000,
        height=0.708,
        lights_height=1.99,
        model_descr=TableModelDescr(name="snooker_generic"),
    ),
    # https://web.archive.org/web/20130801042614/http://www.umb.org/Rules/Carom_Rules.pdf
    TableName.BILLIARD_WIP: BilliardTableSpecs(
        l=2.84,
        w=2.84 / 2,
        cushion_width=2 * 2.54 / 100,
        cushion_height=0.037,
        height=0.708,
        lights_height=1.99,
        model_descr=TableModelDescr.null(),
    ),
    TableName.SUMTOTHREE_WIP: BilliardTableSpecs(
        l=2.84,
        w=2.84 / 2,
        cushion_width=2 * 2.54 / 100,
        cushion_height=0.037,
        height=0.708,
        lights_height=1.99,
        model_descr=TableModelDescr.null(),
    ),
    # Russian pyramid («пирамида»), 12 ft table.
    #
    # Playing surface (cushion nose to cushion nose): 370 x 180 cm per the task
    # specification. Ball diameter is 67 mm, making the pocket mouths extremely
    # tight relative to the ball: corner mouth 72.5 mm (midpoint of the 72-73 mm
    # band), middle mouth 82.5 mm (midpoint of the 82-83 mm band). Pocket depth,
    # radius and jaw-radius values are chosen to be geometrically consistent with
    # those tight mouths (pocket radius must exceed half the mouth width); they
    # follow the deep, straight-jawed pocket style of Russian pyramid tables.
    TableName.RUSSIAN_PYRAMID_GENERIC: PocketTableSpecs(
        l=3.70,
        w=1.80,
        cushion_width=0.05,
        cushion_height=0.64 * 2 * 0.0335,  # 0.64 x ball diameter (67 mm)
        corner_pocket_width=0.0725,
        corner_pocket_angle=0,
        corner_pocket_depth=0.045,
        corner_pocket_radius=0.045,
        corner_jaw_radius=0.015,
        side_pocket_width=0.0825,
        side_pocket_angle=0,
        side_pocket_depth=0.05,
        side_pocket_radius=0.044,
        side_jaw_radius=0.008,
        height=0.82,
        lights_height=1.99,
        model_descr=TableModelDescr.null(),
    ),
}


_default_table_type_map: dict[TableType, TableName] = {
    TableType.POCKET: TableName.SEVEN_FOOT_SHOWOOD,
    TableType.SNOOKER: TableName.SNOOKER_GENERIC,
    TableType.BILLIARD: TableName.BILLIARD_WIP,
}

_default_game_type_map: dict[GameType, TableName] = {
    GameType.EIGHTBALL: TableName.SEVEN_FOOT_SHOWOOD,
    GameType.NINEBALL: TableName.SEVEN_FOOT_SHOWOOD,
    GameType.SNOOKER: TableName.SNOOKER_GENERIC,
    GameType.THREECUSHION: TableName.BILLIARD_WIP,
    GameType.SUMTOTHREE: TableName.SUMTOTHREE_WIP,
    GameType.RUSSIAN_PYRAMID_FREE: TableName.RUSSIAN_PYRAMID_GENERIC,
    GameType.RUSSIAN_PYRAMID_COMBINED: TableName.RUSSIAN_PYRAMID_GENERIC,
    GameType.RUSSIAN_PYRAMID_DYNAMIC: TableName.RUSSIAN_PYRAMID_GENERIC,
    GameType.RUSSIAN_PYRAMID_CLASSIC: TableName.RUSSIAN_PYRAMID_GENERIC,
}


def default_specs_from_table_type(table_type: TableType) -> TableSpecs:
    return prebuilt_specs(_default_table_type_map[table_type])


def default_specs_from_game_type(game_type: GameType) -> TableSpecs:
    return prebuilt_specs(_default_game_type_map[game_type])


def prebuilt_specs(name: TableName) -> TableSpecs:
    return TABLE_SPECS[name]
