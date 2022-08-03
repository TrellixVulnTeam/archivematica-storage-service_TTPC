# -*- coding: utf-8 -*-
from __future__ import absolute_import
import logging
import os
import six
import subprocess

from django.db import models
from django.utils.translation import ugettext_lazy as _

from common import utils

from . import StorageException
from .location import Location

LOGGER = logging.getLogger(__name__)


class RClone(models.Model):
    """Space for storing packages in a variety of systems using rclone."""

    space = models.OneToOneField("Space", to_field="uuid", on_delete=models.CASCADE)

    remote_name = models.CharField(
        max_length=64,
        verbose_name=_("Remote Name"),
        blank=True,
        help_text=_("Must match rclone environment variables"),
    )
    container = models.CharField(
        max_length=64,
        verbose_name=_("Bucket or Container Name"),
        blank=True,
        help_text=_("S3 bucket or object store container name"),
    )

    class Meta:
        verbose_name = _("RClone")
        app_label = _("locations")

    # TODO: Add support for Transfer Source?
    ALLOWED_LOCATION_PURPOSE = [
        Location.AIP_STORAGE,
        Location.DIP_STORAGE,
        Location.REPLICATOR,
    ]

    def _execute_subprocess(self, subcommand):
        """Execute subprocess command.

        :param subcommand: command to execute (list)

        :returns: stdout returned by rclone
        :throws: StorageException on non-zero exit code
        """
        cmd = ["rclone"] + subcommand
        try:
            with subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            ) as proc:
                (stdout, stderr) = proc.communicate()

                LOGGER.debug("rclone cmd: %s", cmd)
                LOGGER.debug("rclone stdout: %s", stdout)
                if stderr:
                    LOGGER.warning(stderr)

                return stdout, stderr
        except FileNotFoundError as err:
            err_msg = "rclone executable not found at path. Details: {}".format(err)
            LOGGER.error(err_msg)
            raise StorageException(err_msg)
        except Exception as err:
            err_msg = (
                "Error running rclone command. Command called: {}. Details: {}".format(
                    cmd, err
                )
            )
            LOGGER.error(err_msg)
            raise StorageException(err_msg)

    @property
    def remote_prefix(self):
        """Return first remote prefix from rclone config (e.g. `local:`).

        TODO: This assumes there is only one remote, which will prevent
        multiple RClone Spaces from being used concurrently. Eventually we
        should parse this in a more sophisticated way, perhaps comparing
        each remote's name against a name field on the model.
        """
        remotes, _ = self._execute_subprocess(["listremotes"])
        LOGGER.debug("rclone listremotes output: %s", remotes)
        remotes = six.ensure_str(remotes).split("\n")

        for remote in remotes:
            if remote.startswith(self.remote_name.lower()):
                LOGGER.debug("rclone remote selected: %s", remote)
                return remote

        raise StorageException("rclone remote matching %s not found", self.remote_name)

    def _ensure_container_exists(self):
        """Ensure that the S3 bucket or other container exists by asking it
        something about itself. If we cannot retrieve metadata about it then
        we attempt to create the bucket, else, we raise a StorageException.
        """
        LOGGER.debug("Test that container '%s' exists", self.container)
        prefixed_container_name = "{}{}".format(self.remote_prefix, self.container)
        cmd = ["ls", prefixed_container_name]
        _, stderr = self._execute_subprocess(cmd)
        if stderr:
            LOGGER.info("Creating container '%s'", self.container)
            create_container_cmd = ["mkdir", prefixed_container_name]
            _, stderr = self._execute_subprocess(create_container_cmd)
            if stderr:
                err_msg = "Unable to find or create container {}".format(
                    prefixed_container_name
                )
                LOGGER.error(err_msg)
                raise StorageException(err_msg)

    # TODO: Implement browse
    def browse(self, path):
        """
        Returns a dictionary with keys 'entries', 'directories' and 'properties'.

        'entries' is a list of strings, one for each entry in that directory, both file-like and folder-like.
        'directories' is a list of strings for each folder-like entry. Each entry should also be listed in 'entries'.
        'properties' is a dictionary that may contain additional information for the entries.  Keys are the entry name found in 'entries', values are a dictionary containing extra information. 'properties' may not contain all values from 'entries'.

        E.g.
        {
            'entries': ['BagTransfer.zip', 'Images', 'Multimedia', 'OCRImage'],
            'directories': ['Images', 'Multimedia', 'OCRImage'],
            'properties': {
                'Images': {'object count': 10},
                'Multimedia': {'object count': 7},
                'OCRImage': {'object count': 1}
            },
        }

        Values in the properties dict vary depending on the providing Space but may include:
        'size': Size of the object
        'object count': Number of objects in the directory, including children
        'timestamp': Last modified timestamp.
        'verbose name': Verbose name of the object
        See each Space's browse for details.

        :param str path: Full path to return info for
        :return: Dictionary of object information detailed above.
        """
        raise NotImplementedError(_("RClone space does not yet implement browse"))

    def delete_path(self, delete_path):
        if delete_path.startswith(os.sep):
            LOGGER.info(
                "Rclone path to delete {} begins with {}; removing from path prior to deletion".format(
                    delete_path, os.sep
                )
            )
            delete_path = delete_path.lstrip(os.sep)
        if self.container:
            delete_path = "{}{}{}".format(
                self.remote_prefix, self.container + "/", delete_path.lstrip("/")
            )
        cmd = ["delete", delete_path]
        _, stderr = self._execute_subprocess(cmd)
        if stderr:
            err_msg = "Unable to delete package at path {}".format(delete_path)
            LOGGER.error(err_msg)
            raise StorageException(err_msg)

    def move_to_storage_service(self, src_path, dest_path, dest_space):
        """ Moves src_path to dest_space.staging_path/dest_path. """
        # strip leading slash on src_path
        src_path = src_path.rstrip(".")
        dest_path = dest_path.rstrip(".")

        subcommand = "copyto"
        if not utils.package_is_file(src_path):
            subcommand = "copy"

        container = ""
        if self.container:
            self._ensure_container_exists()
            container = self.container + "/"
            src_path = src_path.lstrip("/")

        # Directories need to have trailing slashes to ensure they are created
        # on the staging path.
        if not utils.package_is_file(dest_path):
            dest_path = os.path.join(dest_path, "")

        cmd = [
            subcommand,
            "{}{}{}".format(self.remote_prefix, container, src_path),
            dest_path,
        ]
        self._execute_subprocess(cmd)

    def move_from_storage_service(self, src_path, dest_path, package=None):
        """ Moves self.staging_path/src_path to dest_path."""
        if not self.container:
            self.space.create_local_directory(dest_path)
        subcommand = "copyto"
        if not utils.package_is_file(src_path):
            subcommand = "copy"

        container = ""
        if self.container:
            self._ensure_container_exists()
            container = self.container + "/"
            dest_path = dest_path.lstrip("/")

        cmd = [
            subcommand,
            src_path,
            "{}{}{}".format(self.remote_prefix, container, dest_path),
        ]
        self._execute_subprocess(cmd)
