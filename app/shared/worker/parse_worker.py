import asyncio
import logging
import threading
from queue import Queue

from app.module.db_module.service import DBService
from app.shared.aliyun.service.oss_service import OSSClient
from canary_framework import service, on_init, on_start, on_end, Context, config

logger = logging.getLogger(__name__)


@config
class ParseWorkerConfig:
    parse_worker_max_retries: int = 3


@service(name="ParseWorker", deps=[DBService, OSSClient], config=ParseWorkerConfig)
class ParseWorker:
    @on_init
    def init(self, ctx: Context):
        self._queue: Queue = Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_retries = ctx.config.parse_worker_max_retries
        self._running = True

    @on_start
    async def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("ParseWorker thread started")

    @on_end
    async def end(self):
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("ParseWorker shutdown")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._worker_loop())

    async def _worker_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1)
            except Exception:
                continue
            if item is None:
                break
            await self._process_parse(item)

    def submit(self, item: dict):
        self._queue.put(item)

    async def _process_parse(self, item: dict):
        kb_id = item.get("kb_id")
        file_ids = item.get("file_ids", [])
        task_id = item.get("task_id")

        for file_id in file_ids:
            retries = 0
            while retries < self._max_retries:
                try:
                    async with self.db_service.transaction() as session:
                        file_record_repo = self.db_service.file_record_repo(session)
                        node_repo = self.db_service.node_repo(session)

                        record = await file_record_repo.get_by_file_id(file_id)
                        if not record:
                            logger.warning(f"File record not found: {file_id}")
                            break
                        if record.status != "pending":
                            logger.info(f"File {file_id} already has status {record.status}, skipping")
                            break

                        record.status = "processing"
                        await file_record_repo.update(record)

                    await self._do_parse(file_id, kb_id)

                    async with self.db_service.transaction() as session:
                        file_record_repo = self.db_service.file_record_repo(session)
                        record = await file_record_repo.get_by_file_id(file_id)
                        if record:
                            record.status = "parsed"
                            await file_record_repo.update(record)

                    logger.info(f"Parse completed: file_id={file_id}")
                    break
                except Exception as e:
                    retries += 1
                    logger.error(f"Parse failed (retry {retries}/{self._max_retries}): file_id={file_id}, error={e}")
                    if retries >= self._max_retries:
                        async with self.db_service.transaction() as session:
                            file_record_repo = self.db_service.file_record_repo(session)
                            record = await file_record_repo.get_by_file_id(file_id)
                            if record:
                                record.status = "failed"
                                record.error_msg = str(e)
                                await file_record_repo.update(record)
                    else:
                        await asyncio.sleep(2)

    async def _do_parse(self, file_id: str, kb_id: str):
        async with self.db_service.transaction() as session:
            node_repo = self.db_service.node_repo(session)
            file_record_repo = self.db_service.file_record_repo(session)

            node = await node_repo.get_by_id(file_id)
            if not node or not node.oss_key:
                raise ValueError(f"Node or OSS key not found: {file_id}")

            content = self._download_and_parse(node.oss_key, node.node_type or "txt")

            record = await file_record_repo.get_by_file_id(file_id)
            if record:
                record.parsed_text = content
                await file_record_repo.update(record)

    def _download_and_parse(self, oss_key: str, file_type: str) -> str:
        import tempfile
        import os

        data = self.oss_client.download(oss_key)

        suffix = f".{file_type}" if file_type else ".txt"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            if file_type in ("txt", "md", "markdown"):
                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            else:
                from markitdown import MarkItDown
                md = MarkItDown()
                result = md.convert(tmp_path)
                return result.text_content or ""
        finally:
            os.unlink(tmp_path)
