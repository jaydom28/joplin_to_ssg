import os
import logging

import requests

from typing import Optional, NewType, TypedDict

from DataTypes import ConfigData


FolderID = NewType("FolderID", str)
NoteID = NewType("NoteID", str)
logger = logging.getLogger(__name__)


# Source - https://stackoverflow.com/a/27264385
# Posted by Animesh Sharma
# Retrieved 2026-08-28, License - CC BY-SA 3.0
def normalize(text: str) -> str:
    return text.replace(" ", "-")


class JoplinWebClipper:
    """
    Interacts with the Joplin webclipper API to get note data.
    """
    def __init__(self, port: int, token: str):
        self.port = 41184
        self.base_url = f"http://localhost:{self.port}"
        self.token = token
        self.notes = JoplinWebClipperNotes(self.base_url, self.token)
        self.folders = JoplinWebClipperFolders(self.base_url, self.token)
        self.resources = JoplinWebClipperResources(self.base_url, self.token)
        self.tags = JoplinWebClipperTags(self.base_url, self.token)

    @classmethod
    def from_config_data(cls, data: ConfigData):
        return cls(port=data["joplin_port"], token=data["joplin_token"])

    def ping(self) -> bool:
        url = f"{self.base_url}/ping"

        try:
            res = requests.get(url)
        except requests.exceptions.ConnectionError:
            logger.warning(f"Joplin server did not respond at: {url}")
            return False

        if not res.ok:
            logger.error("Joplin server returned: {res.status_code}")
            return False

        return True

    def resolve_path(self, path: str) -> str:
        *folders, note = path.split("/")
        resolved_folders = [self.folders.get_folder(f, fields="title")["title"] for f in folders]
        resolved_note = self.notes.get_note(note, fields="title")["title"]
        return "/".join(resolved_folders + [resolved_note])


class JoplinWebClipperNotes:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/notes"
        self.token = token

    def get(self, fields: Optional[str] = None):
        url = f"{self.base_url}?token={self.token}"
        res = requests.get(url)

        return res.json()["items"]

    def get_note(self, note: NoteID, fields: Optional[str] = None):
        url = f"{self.base_url}/{note}?token={self.token}"
        if fields is not None:
            url = f"{url}&fields={fields}"
        
        res = requests.get(url)
        return res.json()

    def get_note_body(self, note: NoteID):
        *_, note = note.split("/")
        return self.get_note(note, fields="body")["body"]

    def get_note_path(self, note: NoteID) -> str:
        note = self.get_note(note)
        output = []
        return ""


class JoplinWebClipperFolders:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/folders"
        self.token = token

    def get(self, fields: Optional[str] = None):
        url = f"{self.base_url}?token={self.token}"
        res = requests.get(url)

        return res.json()["items"]

    def get_folder(self, folder: FolderID, fields: Optional[str] = None):
        url = f"{self.base_url}/{folder}?token={self.token}"
        if fields is not None:
            url = f"{url}&fields={fields}"
        
        res = requests.get(url)
        return res.json()

    def get_folder_path(self, folder: FolderID) -> str:
        last = folder
        output = []
        while last:
            tmp = self.get_folder(last)["title"]
            output.append(tmp)
            last = self.get_folder(last)["parent_id"]
        return "/".join(reversed(output))

    def get_subfolders(self, folder: FolderID) -> list:
        return [f for f in self.get() if f["parent_id"] == folder]

    def get_notes(self, folder: FolderID) -> list:
        url = f"{self.base_url}/{folder}/notes?token={self.token}"
        res = requests.get(url)
        return res.json()["items"]

    def find_all_notes(self, folder: FolderID, root: Optional[FolderID] = None) -> list[str]:
        """
        Takes in a folder ID and finds all full note paths under that folder.
        """
        if root:
            root = f"{root}/{folder}"
            notes = [f"{root}/{note['id']}" for note in self.get_notes(folder)]
        else:
            notes = [note["id"] for note in self.get_notes(folder)]
            root = folder

        for sub_folder in self.get_subfolders(folder):
            notes.extend(self.find_all_notes(sub_folder["id"], root))
        return notes


class JoplinWebClipperResources:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/notes"
        self.token = token


class JoplinWebClipperTags:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/notes"
        self.token = token


class HugoGenerator:
    """
    Creates content files in the expected hugo structure.
    """
    def __init__(self, root: str):
        self.root = root

    @classmethod
    def from_config_data(cls, data: ConfigData):
        return cls(root=data["joplin_dst"])

    def read(self, path: str) -> Optional[str]:
        path = self.get_full_path(path)

        if not os.path.exists(path):
            return None

        with open(path, "r") as handle:
            return handle.read()

    def write(self, path: str, data: str) -> bool:
        path = self.get_full_path(path.replace(" ", "-"))
        dirname, basename = os.path.split(path)
        if os.path.isfile(dirname):
            logger.error(f"Unable to write, because {dirname} is a file")
            return False

        if not os.path.isdir(dirname):
            os.makedirs(dirname)

        with open(path, "w") as handle:
            handle.write(data)

        return True

    def get_full_path(self, path: str) -> str:
        return os.path.join(self.root, path, "index.md")
