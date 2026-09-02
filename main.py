import argparse
import logging
import os
import sys
import unicodedata
import yaml

import frontmatter
import requests

from typing import NewType, Optional, TypedDict

from Helpers import JoplinWebClipper, HugoGenerator, normalize
from DataTypes import ConfigData


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.ERROR)


def parse_arguments():
    parser = argparse.ArgumentParser()
    # config file path
    parser.add_argument("-c", "--config-file",
                        type=str,
                        default="~/.joplin_to_ssg.yaml",
                        help="The config file to use, create this file to skip passing in args")

    # port arg
    parser.add_argument("-p", "--joplin-port",
                        type=int,
                        default=41184,
                        help="Joplin webclipper API port.")

    # API token
    parser.add_argument("--joplin-token", type=str, default="",
                        help="Joplin webclipper API access token.")

    # Joplin root
    parser.add_argument("-i", "--joplin-src", type=str, default="",
                        help="The root notebook(folder) to use in joplin.")

    # Local root
    parser.add_argument("-o", "--joplin-dst", type=str, default="",
                        help="The root local folder to create SSG files in.")

    return parser.parse_args()


def read_config_file(file: str) -> ConfigData:
    """
    Create a namespace from the config file, and overwrite any needed variables.
    """
    file = os.path.expanduser(file)

    if not os.path.isfile(file):
        dirname, basename = os.path.split(file)
        os.makedirs(dirname, exist_ok=True)
        with open(file, "w") as handle:
            pass

    with open(file, "r") as handle:
        file_data = yaml.safe_load(handle) or {}

    file_data["file"] = file

    return file_data


def verify_params(data) -> bool:
    required_keys = {"file", "joplin_port", "joplin_src", "joplin_dst", "joplin_token"}

    if not data.get("joplin_token"):
        logger.error("No token provided")
        return False

    return all(data.values()) and (data.keys() == required_keys)


def load_config() -> Optional[ConfigData]:
    """
    Loads configs and takes into account priority
    - config file
    - CLI arguments
    """
    args = parse_arguments()
    data = read_config_file(args.config_file) if args.config_file else {}
    data = {
        "file": data.get("file"),
        "joplin_port": data.get("joplin_port") or args.joplin_port,
        "joplin_token": data.get("joplin_token") or args.joplin_token,
        "joplin_src": data.get("joplin_src") or args.joplin_src,
        "joplin_dst": data.get("joplin_dst") or args.joplin_dst
    }

    return data if verify_params(data) else None


# TODO: Figure out how to link to pictures in hugo
# TODO: Investigate how to create a standard python CLI tool


def main() -> int:
    if (config_data := load_config()) is None:
        print("Missing required parameters")
        return 42
    joplin = JoplinWebClipper.from_config_data(config_data)
    hugo = HugoGenerator.from_config_data(config_data)

    if not joplin.ping():
        print("Unable to connect to joplin.")
        return 42

    folder = next((f for f in joplin.folders.get() if f["title"] == config_data["joplin_src"]), None)
    if folder is None:
        print(f"Unable to find Joplin folder named: {config_data['joplin_src']}")
        return 42

    notes = joplin.folders.find_all_notes(folder["id"])
    resolved_notes = [joplin.resolve_path(p) for p in notes]
    backlink_map = joplin.get_note_references(folder["id"])
    post = joplin.notes.generate_frontmatter("1f5fe0079acd41aa9711d6e2984a634a")

    print(f"Found {len(notes)} notes in: {config_data['joplin_src']}")
    for path in notes:
        frontmatter_note = joplin.generate_frontmatter(hugo, path, backlink_map)
        resolved_path = normalize(joplin.resolve_path(path))

        if hugo.read(resolved_path) == frontmatter.dumps(frontmatter_note):
            logger.info(f"{resolved_path} is already synced to {normalize(joplin.resolve_path(path))}")
            continue

        print(f"Syncing: Joplin:{joplin.resolve_path(path)} --> local:{hugo.get_full_note_path(resolved_path)}")
        hugo.write(resolved_path, frontmatter.dumps(frontmatter_note))

    return 0


if __name__ == "__main__":
    sys.exit(main())
