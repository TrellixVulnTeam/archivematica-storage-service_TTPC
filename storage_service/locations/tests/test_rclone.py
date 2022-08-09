from __future__ import absolute_import
import uuid

import pytest

from locations import models

RCLONE_SPACE_UUID = str(uuid.uuid4())
RCLONE_AS_LOCATION_UUID = str(uuid.uuid4())
RCLONE_AIP_UUID = str(uuid.uuid4())
PIPELINE_UUID = str(uuid.uuid4())

SRC_PATH = "/path/to/aip/src"
DEST_PATH = "/path/to/aip/dest"

MOCK_LSJSON_STDOUT = b'[{"Name":"dir1","IsDir":true,"ModTime":"timevalue1"},{"Name":"dir2","IsDir":true,"ModTime":"timevalue2"},{"Name":"obj1.txt","IsDir":false,"ModTime":"timevalue3","MimeType":"text/plain","Size":1024},{"Name":"obj2.mp4","IsDir":false,"ModTime":"timevalue4","MimeType":"video/mp4","Size":2345567}]'


@pytest.fixture
def rclone_space(db):
    space = models.Space.objects.create(
        uuid=RCLONE_SPACE_UUID,
        access_protocol="RCLONE",
        staging_path="rclonestaging",
    )
    rclone_space = models.RClone.objects.create(
        space=space, remote_name="testremote", container="testcontainer"
    )
    return rclone_space


@pytest.fixture
def rclone_space_no_container(db):
    space = models.Space.objects.create(
        uuid=RCLONE_SPACE_UUID,
        access_protocol="RCLONE",
        staging_path="rclonestaging",
    )
    rclone_space = models.RClone.objects.create(
        space=space, remote_name="testremote", container=""
    )
    return rclone_space


@pytest.fixture
def rclone_aip(db):
    space = models.Space.objects.create(
        uuid=RCLONE_SPACE_UUID,
        access_protocol="RCLONE",
        staging_path="rclonestaging",
    )
    models.RClone.objects.create(
        space=space, remote_name="testremote", container="testcontainer"
    )
    pipeline = models.Pipeline.objects.create(uuid=PIPELINE_UUID)
    aipstore = models.Location.objects.create(
        uuid=RCLONE_AS_LOCATION_UUID, space=space, purpose="AS", relative_path="test"
    )
    models.LocationPipeline.objects.get_or_create(pipeline=pipeline, location=aipstore)
    aip = models.Package.objects.create(
        uuid=RCLONE_AIP_UUID,
        origin_pipeline=pipeline,
        current_location=aipstore,
        current_path="fixtures/small_compressed_bag.zip",
        size=1024,
    )
    return aip


@pytest.fixture
def rclone_aip_no_container(db):
    space = models.Space.objects.create(
        uuid=RCLONE_SPACE_UUID,
        access_protocol="RCLONE",
        staging_path="rclonestaging",
    )
    models.RClone.objects.create(space=space, remote_name="testremote", container="")
    pipeline = models.Pipeline.objects.create(uuid=PIPELINE_UUID)
    aipstore = models.Location.objects.create(
        uuid=RCLONE_AS_LOCATION_UUID, space=space, purpose="AS", relative_path="test"
    )
    models.LocationPipeline.objects.get_or_create(pipeline=pipeline, location=aipstore)
    aip = models.Package.objects.create(
        uuid=RCLONE_AIP_UUID,
        origin_pipeline=pipeline,
        current_location=aipstore,
        current_path="fixtures/small_compressed_bag.zip",
        size=1024,
    )
    return aip


def test_rclone_delete(mocker, rclone_aip):
    """Mock method call and assert correctness of rclone command."""
    delete_path = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    mocker.patch("locations.models.rclone.RClone._ensure_container_exists")

    rclone_aip.delete_from_storage()
    delete_path.assert_called_with(
        ["delete", "testremote:testcontainer/test/fixtures/small_compressed_bag.zip"]
    )


def test_rclone_delete_no_container(mocker, rclone_aip_no_container):
    """Mock method call and assert correctness of rclone command."""
    delete_path = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )

    rclone_aip_no_container.delete_from_storage()
    delete_path.assert_called_with(
        ["delete", "testremote:test/fixtures/small_compressed_bag.zip"]
    )


@pytest.mark.parametrize(
    "subprocess_returns, creates_container, raises_storage_exception",
    [
        # Test case where container already exists - first call returns no stderr.
        ([(None, None)], False, False),
        # Test case where container doesn't exist but is created on second call.
        ([(None, "error"), (None, None)], True, False),
        # Test case where container doesn't exist and creating fails.
        ([(None, "error"), (None, "error")], True, True),
    ],
)
def test_rclone_ensure_container_exists(
    mocker,
    rclone_space,
    subprocess_returns,
    creates_container,
    raises_storage_exception,
):
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    execute_subprocess = mocker.patch(
        "locations.models.rclone.RClone._execute_subprocess"
    )
    execute_subprocess.side_effect = subprocess_returns

    if not raises_storage_exception:
        rclone_space._ensure_container_exists()
        assert execute_subprocess.call_count == len(subprocess_returns)
        if creates_container:
            execute_subprocess.assert_called_with(["mkdir", "testremote:testcontainer"])
    else:
        with pytest.raises(models.StorageException):
            rclone_space._ensure_container_exists()
            execute_subprocess.assert_called_with(["mkdir", "testremote:testcontainer"])


@pytest.mark.parametrize(
    "listremotes_return, expected_return, raises_storage_exception",
    [
        # One matching remote returned from listremotes.
        ((b"testremote:\n", None), "testremote:", False),
        # Several remotes returned from listremotes, including a match.
        ((b"another-remote:\ntestremote:\n", None), "testremote:", False),
        # Several remotes returned from listremotes, no match.
        ((b"another-remote:\nnon-matching-remote:\n", None), None, True),
    ],
)
def test_rclone_remote_prefix(
    mocker, rclone_space, listremotes_return, expected_return, raises_storage_exception
):
    execute_subprocess = mocker.patch(
        "locations.models.rclone.RClone._execute_subprocess"
    )
    execute_subprocess.return_value = listremotes_return

    if not raises_storage_exception:
        remote_prefix = rclone_space.remote_prefix
        assert remote_prefix == expected_return
    else:
        with pytest.raises(models.StorageException):
            rclone_space.remote_prefix


@pytest.mark.parametrize(
    "subprocess_return, exception_raised",
    [
        # Test that stdout and stderr are returned.
        (("stdout", "stderr"), False),
        # Test that exception results in StorageException.
        ((None, "stderr"), True),
    ],
)
def test_rclone_execute_subprocess(
    mocker, rclone_space, subprocess_return, exception_raised
):
    subcommand = ["listremotes"]

    if exception_raised:
        with pytest.raises(models.StorageException):
            rclone_space._execute_subprocess(subcommand)
    else:
        subprocess = mocker.patch("locations.models.rclone.subprocess")
        subprocess.Popen.return_value.__enter__.return_value.communicate.return_value = (
            subprocess_return
        )
        return_value = rclone_space._execute_subprocess(subcommand)
        assert return_value == subprocess_return


@pytest.mark.parametrize(
    "package_is_file, expected_subcommand",
    [
        # Package is file, expect "copyto" subcommand
        (
            True,
            [
                "copyto",
                "testremote:testcontainer/{}".format(SRC_PATH.lstrip("/")),
                DEST_PATH,
            ],
        ),
        # Package is directory, expect "copy" subcommand
        (
            False,
            [
                "copy",
                "testremote:testcontainer/{}".format(SRC_PATH.lstrip("/")),
                DEST_PATH + "/",
            ],
        ),
    ],
)
def test_rclone_move_to_storage_service(
    mocker, rclone_space, package_is_file, expected_subcommand
):
    exec_subprocess = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    mocker.patch("locations.models.rclone.RClone._ensure_container_exists")
    mocker.patch("common.utils.package_is_file", return_value=package_is_file)

    rclone_space.move_to_storage_service(SRC_PATH, DEST_PATH, rclone_space)
    exec_subprocess.assert_called_with(expected_subcommand)


@pytest.mark.parametrize(
    "package_is_file, expected_subcommand",
    [
        # Package is file, expect "copyto" subcommand
        (True, ["copyto", "testremote:{}".format(SRC_PATH.lstrip("/")), DEST_PATH]),
        # Package is directory, expect "copy" subcommand
        (
            False,
            ["copy", "testremote:{}".format(SRC_PATH.lstrip("/")), DEST_PATH + "/"],
        ),
    ],
)
def test_rclone_move_to_storage_service_no_container(
    mocker, rclone_space_no_container, package_is_file, expected_subcommand
):
    exec_subprocess = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    mocker.patch("common.utils.package_is_file", return_value=package_is_file)

    rclone_space_no_container.move_to_storage_service(SRC_PATH, DEST_PATH, rclone_space)
    exec_subprocess.assert_called_with(expected_subcommand)


@pytest.mark.parametrize(
    "package_is_file, expected_subcommand",
    [
        # Package is file, expect "copyto" subcommand
        (
            True,
            [
                "copyto",
                SRC_PATH,
                "testremote:testcontainer/{}".format(DEST_PATH.lstrip("/")),
            ],
        ),
        # Package is directory, expect "copy" subcommand
        (
            False,
            [
                "copy",
                SRC_PATH,
                "testremote:testcontainer/{}".format(DEST_PATH.lstrip("/")),
            ],
        ),
    ],
)
def test_rclone_move_from_storage_service(
    mocker, rclone_space, package_is_file, expected_subcommand
):
    exec_subprocess = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    mocker.patch("locations.models.rclone.RClone._ensure_container_exists")
    mocker.patch("common.utils.package_is_file", return_value=package_is_file)

    rclone_space.move_from_storage_service(SRC_PATH, DEST_PATH, rclone_space)
    exec_subprocess.assert_called_with(expected_subcommand)


@pytest.mark.parametrize(
    "package_is_file, expected_subcommand",
    [
        # Package is file, expect "copyto" subcommand
        (True, ["copyto", SRC_PATH, "testremote:{}".format(DEST_PATH.lstrip("/"))]),
        # Package is directory, expect "copy" subcommand
        (
            False,
            [
                "copy",
                SRC_PATH,
                "testremote:{}".format(DEST_PATH.lstrip("/")),
            ],
        ),
    ],
)
def test_rclone_move_from_storage_service_no_container(
    mocker, rclone_space_no_container, package_is_file, expected_subcommand
):
    exec_subprocess = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    mocker.patch("common.utils.package_is_file", return_value=package_is_file)

    rclone_space_no_container.move_from_storage_service(SRC_PATH, DEST_PATH)
    exec_subprocess.assert_called_with(expected_subcommand)


@pytest.mark.parametrize(
    "subprocess_return, expected_properties, raises_storage_exception",
    [
        # Test with stdout as expected.
        (
            (MOCK_LSJSON_STDOUT, None),
            {
                "dir1": {"timestamp": "timevalue1"},
                "dir2": {"timestamp": "timevalue2"},
                "obj1.txt": {
                    "size": 1024,
                    "timestamp": "timevalue3",
                    "mimetype": "text/plain",
                },
                "obj2.mp4": {
                    "size": 2345567,
                    "timestamp": "timevalue4",
                    "mimetype": "video/mp4",
                },
            },
            False,
        ),
        # Test that stderr raises exception
        ((None, "error"), None, True),
    ],
)
def test_rclone_browse(
    mocker,
    rclone_space,
    subprocess_return,
    expected_properties,
    raises_storage_exception,
):
    exec_subprocess = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    exec_subprocess.return_value = subprocess_return
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )
    mocker.patch("locations.models.rclone.RClone._ensure_container_exists")

    if not raises_storage_exception:
        return_value = rclone_space.browse("/")
        assert sorted(return_value["directories"]) == ["dir1", "dir2"]
        assert sorted(return_value["entries"]) == [
            "dir1",
            "dir2",
            "obj1.txt",
            "obj2.mp4",
        ]
        assert return_value["properties"] == expected_properties
    else:
        with pytest.raises(models.StorageException):
            _ = rclone_space.browse("/")


@pytest.mark.parametrize(
    "subprocess_return, expected_properties, raises_storage_exception",
    [
        # Test with stdout as expected.
        (
            (MOCK_LSJSON_STDOUT, None),
            {
                "dir1": {"timestamp": "timevalue1"},
                "dir2": {"timestamp": "timevalue2"},
                "obj1.txt": {
                    "size": 1024,
                    "timestamp": "timevalue3",
                    "mimetype": "text/plain",
                },
                "obj2.mp4": {
                    "size": 2345567,
                    "timestamp": "timevalue4",
                    "mimetype": "video/mp4",
                },
            },
            False,
        ),
        # Test that stderr raises exception
        ((None, "error"), None, True),
    ],
)
def test_rclone_browse_no_container(
    mocker,
    rclone_space_no_container,
    subprocess_return,
    expected_properties,
    raises_storage_exception,
):
    exec_subprocess = mocker.patch("locations.models.rclone.RClone._execute_subprocess")
    exec_subprocess.return_value = subprocess_return
    mocker.patch(
        "locations.models.rclone.RClone.remote_prefix",
        return_value="testremote:",
        new_callable=mocker.PropertyMock,
    )

    if not raises_storage_exception:
        return_value = rclone_space_no_container.browse("/")
        assert sorted(return_value["directories"]) == ["dir1", "dir2"]
        assert sorted(return_value["entries"]) == [
            "dir1",
            "dir2",
            "obj1.txt",
            "obj2.mp4",
        ]
        assert return_value["properties"] == expected_properties
    else:
        with pytest.raises(models.StorageException):
            _ = rclone_space_no_container.browse("/")
