import logging

import oss2
from canary_framework import service, after_config

logger = logging.getLogger(__name__)


@service(name="OSSClient")
class OSSClient:
    @after_config
    def setup(self):
        self._endpoint = self.config.oss_endpoint
        self._region = self.config.oss_region
        self._bucket_name = self.config.oss_bucket
        auth = oss2.Auth(self.config.oss_access_key, self.config.oss_secret_key)
        self._bucket = oss2.Bucket(auth, self.config.oss_endpoint, self.config.oss_bucket)

    @property
    def bucket(self) -> oss2.Bucket:
        return self._bucket

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        self._bucket.put_object(key, data, headers=headers)
        return self.get_url(key)

    def download(self, key: str) -> bytes:
        result = self._bucket.get_object(key)
        return result.read()

    def get_url(self, key: str) -> str:
        return f"https://{self._bucket_name}.{self._endpoint}/{key}"

    def delete(self, key: str) -> None:
        self._bucket.delete_object(key)

    def build_key(self, user_id: str, username: str, kb_id: str, full_path: str) -> str:
        clean_path = full_path.lstrip("/")
        return f"ai/knowledge-base/{user_id}_{username}/{kb_id}/{clean_path}"
