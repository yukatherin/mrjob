# Copyright 2009-2013 Yelp and Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import bz2
import os

try:
    import boto
    boto  # pyflakes
except ImportError:
    boto = None

from mrjob.fs.s3 import S3Filesystem
from mrjob.fs.s3 import _get_bucket

from tests.compress import gzip_compress
from tests.mockboto import MockS3Connection
from tests.mockboto import add_mock_s3_data
from tests.py2 import Mock
from tests.py2 import TestCase
from tests.py2 import patch
from tests.sandbox import SandboxedTestCase


class S3FSTestCase(SandboxedTestCase):

    def setUp(self):
        self.sandbox_boto()
        self.addCleanup(self.unsandbox_boto)
        self.fs = S3Filesystem('key_id', 'secret', 'nowhere')

    def sandbox_boto(self):
        self.mock_s3_fs = {}

        def mock_boto_connect_s3(*args, **kwargs):
            kwargs['mock_s3_fs'] = self.mock_s3_fs
            return MockS3Connection(*args, **kwargs)

        self._real_boto_connect_s3 = boto.connect_s3
        boto.connect_s3 = mock_boto_connect_s3

        # copy the old environment just to be polite
        self._old_environ = os.environ.copy()

    def unsandbox_boto(self):
        boto.connect_s3 = self._real_boto_connect_s3

    def add_mock_s3_data(self, bucket, path, contents, time_modified=None):
        """Update self.mock_s3_fs with a map from bucket name
        to key name to data."""
        add_mock_s3_data(self.mock_s3_fs,
                         {bucket: {path: contents}},
                         time_modified)
        return 's3://%s/%s' % (bucket, path)

    def test_cat_uncompressed(self):
        remote_path = self.add_mock_s3_data(
            'walrus', 'data/foo', b'foo\nfoo\n')

        self.assertEqual(list(self.fs._cat_file(remote_path)),
                         [b'foo\n', b'foo\n'])

    def test_cat_bz2(self):
        remote_path = self.add_mock_s3_data(
            'walrus', 'data/foo.bz2', bz2.compress(b'foo\n' * 1000))

        self.assertEqual(list(self.fs._cat_file(remote_path)),
                         [b'foo\n'] * 1000)

    def test_cat_gz(self):
        remote_path = self.add_mock_s3_data(
            'walrus', 'data/foo.gz', gzip_compress(b'foo\n' * 10000))

        self.assertEqual(list(self.fs._cat_file(remote_path)),
                         [b'foo\n'] * 10000)

    def test_ls_basic(self):
        remote_path = self.add_mock_s3_data(
            'walrus', 'data/foo', b'foo\nfoo\n')

        self.assertEqual(list(self.fs.ls(remote_path)), [remote_path])
        self.assertEqual(list(self.fs.ls('s3://walrus/')), [remote_path])

    def test_ls_recurse(self):
        paths = [
            self.add_mock_s3_data('walrus', 'data/bar', b'bar\nbar\n'),
            self.add_mock_s3_data('walrus', 'data/bar/baz', b'baz\nbaz\n'),
            self.add_mock_s3_data('walrus', 'data/foo', b'foo\nfoo\n'),
        ]

        self.assertEqual(list(self.fs.ls('s3://walrus/')), paths)
        self.assertEqual(list(self.fs.ls('s3://walrus/*')), paths)

    def test_ls_glob(self):
        paths = [
            self.add_mock_s3_data('walrus', 'data/bar', b'bar\nbar\n'),
            self.add_mock_s3_data('walrus', 'data/bar/baz', b'baz\nbaz\n'),
            self.add_mock_s3_data('walrus', 'data/foo', b'foo\nfoo\n'),
        ]

        self.assertEqual(list(self.fs.ls('s3://walrus/*/baz')), [paths[1]])

    def test_ls_s3n(self):
        paths = [
            self.add_mock_s3_data('walrus', 'data/bar', b'abc123'),
            self.add_mock_s3_data('walrus', 'data/baz', b'123abc')
        ]

        self.assertEqual(list(self.fs.ls('s3n://walrus/data/*')),
                         [p.replace('s3://', 's3n://') for p in paths])

    def test_du(self):
        paths = [
            self.add_mock_s3_data('walrus', 'data/foo', b'abcd'),
            self.add_mock_s3_data('walrus', 'data/bar/baz', b'defg'),
        ]
        self.assertEqual(self.fs.du('s3://walrus/'), 8)
        self.assertEqual(self.fs.du(paths[0]), 4)
        self.assertEqual(self.fs.du(paths[1]), 4)

    def test_path_exists_no(self):
        path = os.path.join('s3://walrus/data/foo')
        self.assertEqual(self.fs.path_exists(path), False)

    def test_path_exists_yes(self):
        path = self.add_mock_s3_data('walrus', 'data/foo', b'abcd')
        self.assertEqual(self.fs.path_exists(path), True)

    def test_rm(self):
        path = self.add_mock_s3_data('walrus', 'data/foo', b'abcd')
        self.assertEqual(self.fs.path_exists(path), True)

        self.fs.rm(path)
        self.assertEqual(self.fs.path_exists(path), False)


class GetBucketTestCase(TestCase):

    def assert_bucket_validation(self, boto_version, should_validate):
        with patch('boto.Version', boto_version):
            s3_conn = Mock()
            _get_bucket(s3_conn, 'walrus')
            s3_conn.get_bucket.assert_called_once_with(
                'walrus', validate=should_validate)

    def test_boto_2_2_0(self):
        self.assert_bucket_validation('2.2.0', False)

    def test_boto_2_3_0(self):
        # original version check used string comparison, which
        # would determine that 2.3.0 >= 2.25.0
        self.assertGreaterEqual('2.3.0', '2.25.0')
        self.assert_bucket_validation('2.3.0', False)

    def test_boto_2_25_0(self):
        self.assert_bucket_validation('2.25.0', True)
