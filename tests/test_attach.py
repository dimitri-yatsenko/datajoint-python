from nose.tools import assert_true, assert_equal, assert_not_equal
from numpy.testing import assert_array_equal
import tempfile
import filecmp
import os

from .schema_external import Attach


def test_attach_attributes():
    """ test saving files in attachments """
    # create a mock file
    table = Attach()
    source_folder = tempfile.mkdtemp()
    for i in range(2):
        attach1 = os.path.join(source_folder, 'attach1.img')
        data1 = os.urandom(100)
        with open(attach1, 'wb') as f:
            f.write(data1)
        attach2 = os.path.join(source_folder, 'attach2.txt')
        data2 = os.urandom(200)
        with open(attach2, 'wb') as f:
            f.write(data2)
        table.insert1(dict(attach=i, img=attach1, txt=attach2))

    download_folder = tempfile.mkdtemp()
    keys, path1, path2 = table.fetch("KEY", 'img', 'txt', download_path=download_folder, order_by="KEY")

    # verify that different attachment are renamed if their filenames collide
    assert_not_equal(path1[0], path2[0])
    assert_not_equal(path1[0], path1[1])
    assert_equal(os.path.split(path1[0])[0], download_folder)
    with open(path1[-1], 'rb') as f:
        check1 = f.read()
    with open(path2[-1], 'rb') as f:
        check2 = f.read()
    assert_equal(data1, check1)
    assert_equal(data2, check2)

    # verify that existing files are not duplicated if their filename matches issue #592
    p1, p2 = (Attach & keys[0]).fetch1('img', 'txt', download_path=download_folder)
    assert_equal(p1, path1[0])
    assert_equal(p2, path2[0])

