from typing import TypedDict, Optional


class ConfigData(TypedDict):
    """
    Holds the variables loaded from a config file
    """
    file: Optional[str]
    joplin_port: int
    joplin_token: str
    joplin_src: str
    joplin_dst: str
