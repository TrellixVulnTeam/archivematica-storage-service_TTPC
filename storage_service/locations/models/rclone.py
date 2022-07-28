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

    class Meta:
        verbose_name = _("RClone")
        app_label = _("locations")

    # TODO: Add support for DIP Storage and Transfer Source as well?
    ALLOWED_LOCATION_PURPOSE = [Location.AIP_STORAGE, Location.REPLICATOR]

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

                return stdout
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
        """Return first remote prefix from rclone config (e.g. `local:`."""
        remotes = six.ensure_str(
            self._execute_subprocess(["listremotes"]), errors="ignore"
        )
        LOGGER.debug("rclone listremotes output: %s", remotes)
        return remotes.split("\n")[0]

    # TODO: Implement browse
    # Question: Is this necessary if space isn't used as Transfer Source?
    def browse(self, path):
        raise NotImplementedError(_("RClone space does not yet implement browse"))

    # TODO: Implement deletion
    def delete_path(self, delete_path):
        raise NotImplementedError(_("RClone space does not yet implement deletion"))

    def move_to_storage_service(self, src_path, dest_path, dest_space):
        """ Moves src_path to dest_space.staging_path/dest_path. """
        # strip leading slash on src_path
        src_path = src_path.rstrip(".")
        dest_path = dest_path.rstrip(".")

        subcommand = "copyto"
        if not utils.package_is_file(src_path):
            subcommand = "copy"

        # Directories need to have trailing slashes to ensure they are created
        # on the staging path.
        if not utils.package_is_file(dest_path):
            dest_path = os.path.join(dest_path, "")

        cmd = [
            subcommand,
            "{}{}".format(self.remote_prefix, src_path),
            dest_path,
        ]
        self._execute_subprocess(cmd)

    def move_from_storage_service(self, src_path, dest_path, package=None):
        """ Moves self.staging_path/src_path to dest_path."""
        self.space.create_local_directory(dest_path)
        subcommand = "copyto"
        if not utils.package_is_file(src_path):
            subcommand = "copy"
        cmd = [
            subcommand,
            src_path,
            "{}{}".format(self.remote_prefix, dest_path),
        ]
        self._execute_subprocess(cmd)
