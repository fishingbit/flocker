# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""Functional tests for the ``flocker-volume`` command line tool."""

from subprocess import check_output, Popen, PIPE
import json
from unittest import skipUnless

from twisted.trial.unittest import TestCase
from twisted.python.filepath import FilePath
from twisted.python.procutils import which

from ... import __version__
from ...testtools import skip_on_broken_permissions, attempt_effective_uid
from ..testtools import create_zfs_pool

_require_installed = skipUnless(which("flocker-volume"),
                                "flocker-volume not installed")


def run(*args):
    """Run ``flocker-volume`` with the given arguments.

    :param args: Additional command line arguments as ``bytes``.

    :return: The output of standard out.
    :raises: If exit code is not 0.
    """
    return check_output([b"flocker-volume"] + list(args))


def run_expecting_error(*args):
    """Run ``flocker-volume`` with the given arguments.

    :param args: Additional command line arguments as ``bytes``.

    :return: The output of standard error.
    :raises: If exit code is 0.
    """
    process = Popen([b"flocker-volume"] + list(args), stderr=PIPE)
    result = process.stderr.read()
    exit_code = process.wait()
    if exit_code == 0:
        raise AssertionError("flocker-volume exited with code 0.")
    return result


class FlockerVolumeTests(TestCase):
    """Tests for ``flocker-volume``."""

    @_require_installed
    def setUp(self):
        pass

    def test_version(self):
        """``flocker-volume --version`` returns the current version."""
        result = run(b"--version")
        self.assertEqual(result, b"%s\n" % (__version__,))

    def test_config(self):
        """``flocker-volume --config path`` writes a JSON file at that path."""
        pool = create_zfs_pool(self)
        path = FilePath(self.mktemp())
        run(b"--config", path.path, b"--pool", pool)
        self.assertTrue(json.loads(path.getContent()))

    @skip_on_broken_permissions
    def test_no_permission(self):
        """If the config file is not writeable a meaningful response is
        written.
        """
        path = FilePath(self.mktemp())
        path.makedirs()
        path.chmod(0)
        self.addCleanup(path.chmod, 0o777)
        config = path.child(b"out.json")
        with attempt_effective_uid('nobody', suppress_errors=True):
            result = run_expecting_error(b"--config", config.path)
        self.assertEqual(result,
                         b"Writing config file %s failed: Permission denied\n"
                         % (config.path,))


class FlockerVolumeSnapshotsTests(TestCase):
    """
    Tests for ``flocker-volume snapshots``.
    """
    @_require_installed
    def test_snapshots(self):
        """
        The output of ``flocker-volume snapshots`` is the name of each snapshot
        that exists for the identified filesystem, one per line.
        """
        pool_name = create_zfs_pool(self)
        dataset = pool_name + b"/myuuid.myns.myfilesystem"
        check_output([b"zfs", b"create", b"-p", dataset])
        check_output([b"zfs", b"snapshot", dataset + b"@somesnapshot"])
        check_output([b"zfs", b"snapshot", dataset + b"@lastsnapshot"])
        config_path = FilePath(self.mktemp())
        snapshots = run(
            b"--config", config_path.path,
            b"--pool", pool_name,
            b"snapshots", b"myuuid", b"myns.myfilesystem")
        self.assertEqual(snapshots, b"somesnapshot\nlastsnapshot\n")
