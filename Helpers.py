import logging
import os
import re

import frontmatter
import requests

from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from itertools import count
from typing import Optional, NewType, TypedDict

from DataTypes import ConfigData


FolderID = str
NoteID = str
ResourceID = str
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

    @staticmethod
    def get(url: str) -> Iterator[dict]:
        has_more = True
        page = count(start=0)

        while has_more:
            data = requests.get(f"{url}&page={next(page)}").json()
            has_more = data["has_more"]
            yield from data["items"]

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

    def resolve_path(self, path: NoteID | FolderID) -> str:
        *folders, note = path.split("/")
        resolved_folders = [self.folders.get_folder(f, fields="title")["title"] for f in folders]
        resolved_note = self.notes.get_note(note, fields="title")["title"]
        return "/".join(resolved_folders + [resolved_note])

    def generate_note_body(self, ssg_generator, path: str, backlinks: Optional[dict] = None) -> str:
        """
        Uses the notes endpoint to read the body of a note, but resolves things like:
        - [x] frontmatter
        - [x] resource links
        - [ ] note links
        """
        frontmatter_note = self.notes.generate_frontmatter(path)

        for resource in self.notes.get_note_resources(path):
            resource_file_name = f"{resource['id']}_{resource['title']}"
            resource_path = ssg_generator.get_full_resource_path(resource_file_name)

            # Download the resource to the specified location if it isn't already downloaded
            if not os.path.exists(resource_path):
                self.resources.download_resource(resource["id"], resource_path)

            # Replace references to that joplin resource with references to the download location
            referral_str = f"![{resource['title']}](:/{resource['id']})"
            relative_resource_path = ssg_generator.get_relative_resource_path(resource_file_name)
            resolved_referral_str = f"![{resource['title']}]({relative_resource_path})"
            frontmatter_note.content = frontmatter_note.content.replace(referral_str, resolved_referral_str)

        return frontmatter.dumps(frontmatter_note)

    def get_note_references(self, folder: FolderID) -> dict:
        """
        Read a note and create a map of resources and other notes it refers to in the form:

        {
            "referred_note": [referrer1, referrer2, referrer3, ...]
        }
        """
        ref_map = defaultdict(list)

        for note in self.folders.find_all_notes(folder):
            note_body = self.notes.get_note_body(note)
            ref_ids = re.findall(r"\[.*\]\(:/(.*)\)", note_body)
            for reference in ref_ids:
                ref_map[reference].append(os.path.basename(note))

        return ref_map


class JoplinWebClipperNotes:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/notes"
        self.token = token

    def get(self, fields: Optional[str] = None) -> Iterator[dict]:
        url = f"{self.base_url}?token={self.token}"
        yield from JoplinWebClipper.get(url)

    def get_note_resources(self, note: NoteID) -> list[dict]:
        *_, note = note.split("/")

        url = f"{self.base_url}/{note}/resources?token={self.token}"
        res = requests.get(url)

        return res.json()["items"]

    def get_note(self, note: NoteID, fields: Optional[str] = None) -> dict:
        url = f"{self.base_url}/{note}?token={self.token}"
        if fields is not None:
            url = f"{url}&fields={fields}"
        
        res = requests.get(url)
        return res.json()

    def get_note_tags(self, note: NoteID):
        url = f"{self.base_url}/{note}/tags?token={self.token}"
        res = requests.get(url)
        return res.json()["items"]

    def get_note_body(self, note: NoteID) -> str:
        *_, note = note.split("/")
        return self.get_note(note, fields="body")["body"]

    def get_metadata(self, note: NoteID) -> dict:
        """
        Get the metadata for a note.
        """
        user_created_time = self.get_note(note, fields="user_created_time")["user_created_time"]
        user_updated_time = self.get_note(note, fields="user_updated_time")["user_updated_time"]
        title = self.get_note(note, fields="title")["title"]
        tags = self.get_note_tags(note)
        return {
            "date": datetime.fromtimestamp(user_created_time / 1000),
            "lastmod": datetime.fromtimestamp(user_updated_time / 1000),
            "title": title,
            "tags": [t["title"] for t in tags]
        }

    def generate_frontmatter(self, note: NoteID) -> frontmatter.Post:
        """
        Generate frontmatter metadata from a note.
        """
        *_, note = note.split("/")
        post = frontmatter.loads(self.get_note_body(note))
        post.metadata = {**self.get_metadata(note), **post.metadata}
        return post


class JoplinWebClipperFolders:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/folders"
        self.token = token

    def get(self, fields: Optional[str] = None) -> Iterator[dict]:
        url = f"{self.base_url}?token={self.token}"
        yield from JoplinWebClipper.get(url)

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

    def get_subfolders(self, folder: FolderID) -> Iterator[dict]:
        yield from (f for f in self.get() if f["parent_id"] == folder)

    def get_notes(self, folder: FolderID) -> list:
        url = f"{self.base_url}/{folder}/notes?token={self.token}"
        res = requests.get(url)
        return res.json()["items"]

    def resolve(self, folder: FolderID) -> str:
        if "/" in folder:
            return "/".join(self.get_folder(f, fields="title")["title"] for f in os.path.split(folder))
        return self.get_folder(folder, fields="title")["title"]

    def find_all_notes(self, folder: FolderID, root: Optional[FolderID] = None) -> Iterator[str]:
        """
        Takes in a folder ID and finds all full note paths under that folder.
        """
        notes = [os.path.join(root or "", note["id"]) for note in self.get_notes(folder)]

        for sub_folder in self.get_subfolders(folder):
            yield from self.find_all_notes(sub_folder["id"],
                                           root=os.path.join(root or "", sub_folder["id"]))

        yield from notes


class JoplinWebClipperResources:
    def __init__(self, url: str, token: str):
        self.base_url = f"{url}/resources"
        self.token = token

    def get(self, fields: Optional[str] = None) -> Iterator[dict]:
        url = f"{self.base_url}?token={self.token}"
        yield from JoplinWebClipper.get(url)

    def download_resource(self, resource: ResourceID, download_path: str):
        dirname = os.path.dirname(download_path)
        if not os.path.isdir(dirname):
            os.makedirs(dirname)

        *_, resource = resource.split("/")
        url = f"{self.base_url}/{resource}/file?token={self.token}"
        with requests.get(url, stream=True) as res, open(download_path, "wb") as handle:
            for chunk in res.iter_content(chunk_size=8192):
                handle.write(chunk)


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
        self.root_resources = os.path.join(root, "static", "images", "shared")

    @classmethod
    def from_config_data(cls, data: ConfigData):
        return cls(root=data["joplin_dst"])

    def read(self, path: str) -> Optional[str]:
        path = self.get_full_note_path(path)

        if not os.path.exists(path):
            return None

        with open(path, "r") as handle:
            return handle.read()

    def write(self, path: str, data: str) -> bool:
        path = self.get_full_note_path(path.replace(" ", "-"))
        dirname, basename = os.path.split(path)
        if os.path.isfile(dirname):
            logger.error(f"Unable to write, because {dirname} is a file")
            return False

        if not os.path.isdir(dirname):
            os.makedirs(dirname)

        with open(path, "w") as handle:
            handle.write(data)

        return True

    def get_full_resource_path(self, resource_name: str) -> str:
        return os.path.join(self.root_resources, resource_name)

    def get_relative_resource_path(self, resource_name: str) -> str:
        _, _, _, *remaining = self.root_resources.split("/")
        return "/" + os.path.join(*remaining, resource_name)

    def get_full_note_path(self, path: str) -> str:
        return os.path.join(self.root, path, "index.md")
