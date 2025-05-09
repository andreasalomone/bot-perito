import io

import pytest


# Fixture factory to create dummy upload files with filename and content
@pytest.fixture
def make_dummy_upload():
    def _make_dummy_upload(filename: str, content: bytes):
        class DummyFile:
            def __init__(self):
                self.filename = filename
                self._content = content
                self.file = io.BytesIO(content)

            async def read(self):
                return self._content

        return DummyFile()

    return _make_dummy_upload
